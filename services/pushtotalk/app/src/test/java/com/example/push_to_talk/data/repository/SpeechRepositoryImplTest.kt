package com.example.push_to_talk.data.repository

import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionStatus
import com.example.push_to_talk.domain.model.SpeechEvent
import com.example.push_to_talk.fake.FakeLogger
import com.example.push_to_talk.fake.FakeSpeechEngine
import com.example.push_to_talk.util.MainDispatcherRule
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Проверяет свёртку потока [SpeechEvent] в состояние сессии.
 * Движок подменён [FakeSpeechEngine], поэтому `android.speech.SpeechRecognizer` не нужен.
 */
class SpeechRepositoryImplTest {

    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    private val engine = FakeSpeechEngine()

    private fun TestScope.createRepository() =
        SpeechRepositoryImpl(engine = engine, scope = backgroundScope, logger = FakeLogger())

    @Test
    fun `полный цикл речи завершается финальным текстом`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.Preparing,
            SpeechEvent.ReadyForSpeech,
            SpeechEvent.SpeechStarted,
            SpeechEvent.PartialResult("При"),
            SpeechEvent.PartialResult("Привет"),
            SpeechEvent.SpeechEnded,
            SpeechEvent.FinalResult("Привет"),
        )

        val session = repository.session.value
        assertEquals(RecognitionStatus.Success, session.status)
        assertEquals("Привет", session.finalText)
        assertEquals("Привет", session.displayText)
        assertEquals("", session.partialText)
        assertFalse("Сессия должна быть завершена", session.isActive)
        assertEquals(null, session.error)
    }

    @Test
    fun `промежуточный результат виден до окончания реплики`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.Preparing,
            SpeechEvent.ReadyForSpeech,
            SpeechEvent.SpeechStarted,
            SpeechEvent.PartialResult("При"),
        )

        val session = repository.session.value
        assertEquals("При", session.displayText)
        assertTrue(session.isListening)
        assertTrue(session.isActive)
    }

    @Test
    fun `готовность движка переводит сессию в прослушивание`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(SpeechEvent.Preparing, SpeechEvent.ReadyForSpeech)

        assertEquals(RecognitionStatus.Listening, repository.session.value.status)
        assertTrue(repository.session.value.isListening)
    }

    @Test
    fun `конец речи переводит сессию в распознавание`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.Preparing,
            SpeechEvent.ReadyForSpeech,
            SpeechEvent.SpeechStarted,
            SpeechEvent.SpeechEnded,
        )

        val session = repository.session.value
        assertEquals(RecognitionStatus.Recognizing, session.status)
        assertFalse(session.isListening)
        assertTrue(session.isActive)
    }

    @Test
    fun `уровень сигнала попадает в сессию`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(SpeechEvent.ReadyForSpeech, SpeechEvent.RmsChanged(4.5f))

        assertEquals(4.5f, repository.session.value.rmsDb, 0.001f)
    }

    @Test
    fun `недоступный микрофон завершает сессию ошибкой`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.Preparing,
            SpeechEvent.ReadyForSpeech,
            SpeechEvent.Failed(AppError.Speech.MicrophoneUnavailable),
        )

        val session = repository.session.value
        assertEquals(RecognitionStatus.Error, session.status)
        assertEquals(AppError.Speech.MicrophoneUnavailable, session.error)
        assertFalse(session.isActive)
    }

    @Test
    fun `зависший движок завершает сессию таймаутом`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.Preparing,
            SpeechEvent.ReadyForSpeech,
            // Речь так и не началась — сработал watchdog в SpeechRecognitionManager.
            SpeechEvent.Failed(AppError.Speech.SpeechTimeout),
        )

        val session = repository.session.value
        assertEquals(RecognitionStatus.Error, session.status)
        assertEquals(AppError.Speech.SpeechTimeout, session.error)
    }

    @Test
    fun `отмена сохраняет результат текущей сессии`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.Preparing,
            SpeechEvent.FinalResult("первая реплика"),
            SpeechEvent.Cancelled,
        )

        val session = repository.session.value
        assertEquals(RecognitionStatus.Idle, session.status)
        assertEquals("первая реплика", session.finalText)
        assertFalse(session.isActive)
    }

    @Test
    fun `новая сессия очищает текст предыдущей`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.FinalResult("первая реплика"),
            // Preparing начинает сессию с чистого листа.
            SpeechEvent.Preparing,
        )

        val session = repository.session.value
        assertEquals(RecognitionStatus.Preparing, session.status)
        assertEquals("", session.finalText)
        assertEquals("", session.displayText)
    }

    @Test
    fun `новая сессия очищает ошибку предыдущей`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        engine.emitAll(
            SpeechEvent.Failed(AppError.Speech.NoSpeechDetected),
            SpeechEvent.Preparing,
        )

        val session = repository.session.value
        assertEquals(RecognitionStatus.Preparing, session.status)
        assertEquals(null, session.error)
    }

    @Test
    fun `команды делегируются движку`() = runTest(mainDispatcherRule.testDispatcher) {
        val repository = createRepository()

        repository.start(com.example.push_to_talk.domain.model.RecognitionConfig())
        repository.stop()
        repository.cancel()
        repository.release()

        assertEquals(1, engine.startCount)
        assertEquals(1, engine.stopCount)
        assertEquals(1, engine.cancelCount)
        assertEquals(1, engine.releaseCount)
    }
}
