package com.example.push_to_talk.presentation.main

import com.example.push_to_talk.R
import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionSession
import com.example.push_to_talk.domain.model.RecognitionStatus
import com.example.push_to_talk.domain.model.SpeechEvent
import com.example.push_to_talk.domain.usecase.CancelRecognitionUseCase
import com.example.push_to_talk.domain.usecase.CheckMicrophonePermissionUseCase
import com.example.push_to_talk.domain.usecase.ObserveRecognitionUseCase
import com.example.push_to_talk.domain.usecase.ReleaseRecognitionUseCase
import com.example.push_to_talk.domain.usecase.SendTextUseCase
import com.example.push_to_talk.domain.usecase.StartRecognitionUseCase
import com.example.push_to_talk.domain.usecase.StopRecognitionUseCase
import com.example.push_to_talk.fake.FakeLogger
import com.example.push_to_talk.fake.FakeNetworkGateway
import com.example.push_to_talk.fake.FakePermissionChecker
import com.example.push_to_talk.fake.FakeSpeechRepository
import com.example.push_to_talk.util.MainDispatcherRule
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class MainViewModelTest {

    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    private val speechRepository = FakeSpeechRepository()
    private val network = FakeNetworkGateway()
    private val permissionChecker = FakePermissionChecker()

    private fun TestScope.createViewModel(): MainViewModel {
        val viewModel = MainViewModel(
            observeRecognition = ObserveRecognitionUseCase(speechRepository),
            startRecognition = StartRecognitionUseCase(speechRepository, permissionChecker),
            stopRecognition = StopRecognitionUseCase(speechRepository),
            cancelRecognition = CancelRecognitionUseCase(speechRepository),
            releaseRecognition = ReleaseRecognitionUseCase(speechRepository),
            sendText = SendTextUseCase(network),
            checkMicrophonePermission = CheckMicrophonePermissionUseCase(permissionChecker),
            applicationScope = backgroundScope,
            logger = FakeLogger(),
        )
        // StateFlow собирается только при наличии подписчика.
        backgroundScope.launch { viewModel.uiState.collect { } }
        return viewModel
    }

    @Test
    fun `нажатие на кнопку запускает распознавание`() = runTest(mainDispatcherRule.testDispatcher) {
        val viewModel = createViewModel()

        viewModel.onMicTap()

        assertEquals(1, speechRepository.startCount)
    }

    @Test
    fun `повторное нажатие во время сессии останавливает запись`() = runTest(mainDispatcherRule.testDispatcher) {
        val viewModel = createViewModel()
        speechRepository.setSession(RecognitionSession(status = RecognitionStatus.Listening))

        viewModel.onMicTap()

        assertEquals(1, speechRepository.stopCount)
        assertEquals(0, speechRepository.startCount)
    }

    @Test
    fun `двойное удержание не создаёт вторую сессию и сообщает о занятости`() =
        runTest(mainDispatcherRule.testDispatcher) {
            val viewModel = createViewModel()

            viewModel.onMicPressStart()
            viewModel.onMicPressStart()

            assertEquals(1, speechRepository.startCount)
            assertEquals(AppError.Speech.RecognizerBusy, viewModel.uiState.value.error)
        }

    @Test
    fun `состояние экрана повторяет состояние сессии`() = runTest(mainDispatcherRule.testDispatcher) {
        val viewModel = createViewModel()

        speechRepository.setSession(
            RecognitionSession(
                status = RecognitionStatus.SpeechDetected,
                partialText = "привет",
            ),
        )

        val state = viewModel.uiState.value
        assertEquals(RecognitionStatus.SpeechDetected, state.status)
        assertEquals("привет", state.recognizedText)
        assertTrue(state.isListening)
    }

    @Test
    fun `финальный результат отправляется во внешний сервис`() = runTest(mainDispatcherRule.testDispatcher) {
        val viewModel = createViewModel()

        speechRepository.emitEvent(SpeechEvent.FinalResult("привет мир"))

        assertEquals(listOf("привет мир"), network.sentTexts)
    }

    @Test
    fun `успешная отправка показывает подпись Отправлено`() = runTest(mainDispatcherRule.testDispatcher) {
        val viewModel = createViewModel()

        speechRepository.emitEvent(SpeechEvent.FinalResult("Привет"))

        val state = viewModel.uiState.value
        assertEquals(SendStatus.Success, state.sendStatus)
        assertEquals(R.string.send_status_success, state.sendStatus.messageRes())
        assertFalse(state.isSending)
        assertEquals(null, state.error)
    }

    @Test
    fun `отсутствие сети показывает подпись Ошибка отправки`() = runTest(mainDispatcherRule.testDispatcher) {
        network.result = failure(AppError.Network.NoConnection)
        val viewModel = createViewModel()

        speechRepository.emitEvent(SpeechEvent.FinalResult("привет"))

        val state = viewModel.uiState.value
        assertEquals(SendStatus.Error, state.sendStatus)
        assertEquals(R.string.send_status_error, state.sendStatus.messageRes())
        assertEquals(AppError.Network.NoConnection, state.error)
        assertFalse(state.isSending)
    }

    @Test
    fun `ошибка сервера тоже показывает подпись Ошибка отправки`() = runTest(mainDispatcherRule.testDispatcher) {
        network.result = failure(AppError.Network.Server(500))
        val viewModel = createViewModel()

        speechRepository.emitEvent(SpeechEvent.FinalResult("привет"))

        assertEquals(SendStatus.Error, viewModel.uiState.value.sendStatus)
        assertEquals(AppError.Network.Server(500), viewModel.uiState.value.error)
    }

    @Test
    fun `таймаут показывает подпись Ошибка отправки и снимает индикатор`() =
        runTest(mainDispatcherRule.testDispatcher) {
            network.result = failure(AppError.Network.Timeout)
            val viewModel = createViewModel()

            speechRepository.emitEvent(SpeechEvent.FinalResult("привет"))

            assertEquals(SendStatus.Error, viewModel.uiState.value.sendStatus)
            assertFalse("UI не должен остаться в состоянии отправки", viewModel.uiState.value.isSending)
        }

    @Test
    fun `пустой финальный результат не уходит на сервер`() = runTest(mainDispatcherRule.testDispatcher) {
        val viewModel = createViewModel()

        speechRepository.emitEvent(SpeechEvent.FinalResult(""))

        assertEquals(0, network.callCount)
        assertEquals(AppError.Validation.EmptyText, viewModel.uiState.value.error)
        assertEquals(SendStatus.Error, viewModel.uiState.value.sendStatus)
    }

    @Test
    fun `новая сессия сбрасывает результат прошлой отправки`() = runTest(mainDispatcherRule.testDispatcher) {
        val viewModel = createViewModel()
        speechRepository.emitEvent(SpeechEvent.FinalResult("привет"))
        assertEquals(SendStatus.Success, viewModel.uiState.value.sendStatus)

        viewModel.onMicTap()

        assertEquals(SendStatus.Idle, viewModel.uiState.value.sendStatus)
    }

    @Test
    fun `без разрешения показывается ошибка доступа к микрофону`() = runTest(mainDispatcherRule.testDispatcher) {
        permissionChecker.granted = false
        val viewModel = createViewModel()

        viewModel.onMicTap()

        assertEquals(AppError.Speech.PermissionDenied, viewModel.uiState.value.error)
        assertFalse(viewModel.uiState.value.hasMicrophonePermission)
        assertEquals(0, speechRepository.startCount)
    }

    @Test
    fun `выданное разрешение снимает блокировку экрана`() = runTest(mainDispatcherRule.testDispatcher) {
        permissionChecker.granted = false
        val viewModel = createViewModel()

        permissionChecker.granted = true
        viewModel.onPermissionResult(granted = true)

        assertTrue(viewModel.uiState.value.hasMicrophonePermission)
    }

    @Test
    fun `скрытие ошибки убирает и подпись об ошибке отправки`() = runTest(mainDispatcherRule.testDispatcher) {
        network.result = failure(AppError.Network.NoConnection)
        val viewModel = createViewModel()
        speechRepository.emitEvent(SpeechEvent.FinalResult("привет"))

        viewModel.onErrorDismissed()

        assertEquals(null, viewModel.uiState.value.error)
        assertEquals(SendStatus.Idle, viewModel.uiState.value.sendStatus)
    }
}
