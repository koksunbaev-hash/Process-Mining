package com.example.push_to_talk.presentation.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.result.onFailure
import com.example.push_to_talk.core.result.onSuccess
import com.example.push_to_talk.di.ApplicationScope
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.SpeechEvent
import com.example.push_to_talk.domain.usecase.CancelRecognitionUseCase
import com.example.push_to_talk.domain.usecase.CheckMicrophonePermissionUseCase
import com.example.push_to_talk.domain.usecase.ObserveRecognitionUseCase
import com.example.push_to_talk.domain.usecase.ReleaseRecognitionUseCase
import com.example.push_to_talk.domain.usecase.SendTextUseCase
import com.example.push_to_talk.domain.usecase.StartRecognitionUseCase
import com.example.push_to_talk.domain.usecase.StopRecognitionUseCase
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Единственная ViewModel экрана. Не знает ни про Android Context, ни про SpeechRecognizer:
 * работает только с use case-ами и потоками. Поток данных однонаправленный —
 * состояние сессии и локальные флаги сворачиваются в [MainUiState].
 */
@HiltViewModel
class MainViewModel @Inject constructor(
    private val observeRecognition: ObserveRecognitionUseCase,
    private val startRecognition: StartRecognitionUseCase,
    private val stopRecognition: StopRecognitionUseCase,
    private val cancelRecognition: CancelRecognitionUseCase,
    private val releaseRecognition: ReleaseRecognitionUseCase,
    private val sendText: SendTextUseCase,
    private val checkMicrophonePermission: CheckMicrophonePermissionUseCase,
    @param:ApplicationScope private val applicationScope: CoroutineScope,
    private val logger: Logger,
) : ViewModel() {

    private var pendingDispatchJob: Job? = null

    private val localState = MutableStateFlow(
        LocalState(hasMicrophonePermission = checkMicrophonePermission()),
    )

    val uiState: StateFlow<MainUiState> =
        combine(observeRecognition.session(), localState) { session, local ->
            MainUiState(
                status = session.status,
                recognizedText = session.displayText,
                isListening = session.isListening,
                isSessionActive = session.isActive,
                hasMicrophonePermission = local.hasMicrophonePermission,
                audioLevel = normalizeRms(session.rmsDb),
                sendStatus = local.sendStatus,
                pendingSendSeconds = local.pendingSendSeconds,
                error = local.error ?: session.error,
            )
        }.stateIn(
            scope = viewModelScope,
            started = SharingStarted.WhileSubscribed(STATE_TIMEOUT_MILLIS),
            initialValue = MainUiState(hasMicrophonePermission = localState.value.hasMicrophonePermission),
        )

    init {
        observeRecognition.events()
            .filterIsInstance<SpeechEvent.FinalResult>()
            .onEach { event -> scheduleDispatch(event.text) }
            .launchIn(viewModelScope)
    }

    /** Нажатие в режиме [PushToTalkMode.Tap]: старт или досрочная остановка сессии. */
    fun onMicTap() {
        viewModelScope.launch {
            if (uiState.value.isSessionActive) {
                stopRecognition()
            } else {
                start()
            }
        }
    }

    /** Начало удержания в режиме [PushToTalkMode.Hold]. */
    fun onMicPressStart() {
        viewModelScope.launch { start() }
    }

    /** Отпускание кнопки в режиме [PushToTalkMode.Hold]. */
    fun onMicPressEnd() {
        viewModelScope.launch { stopRecognition() }
    }

    fun onPermissionResult(granted: Boolean) {
        logger.i(TAG, "Разрешение на микрофон: $granted")
        localState.update { it.copy(hasMicrophonePermission = granted) }
    }

    /** Перечитывает разрешение, например после возврата из системных настроек. */
    fun refreshPermission() {
        localState.update { it.copy(hasMicrophonePermission = checkMicrophonePermission()) }
    }

    fun onErrorDismissed() {
        localState.update {
            // Подпись «❌ Ошибка отправки» уходит вместе с самой ошибкой,
            // иначе она осталась бы на экране без объяснения причины.
            val status = if (it.sendStatus == SendStatus.Error) SendStatus.Idle else it.sendStatus
            it.copy(error = null, sendStatus = status)
        }
    }

    fun onPendingSendCancelled() {
        pendingDispatchJob?.cancel()
        pendingDispatchJob = null
        localState.update {
            it.copy(sendStatus = SendStatus.Cancelled, pendingSendSeconds = 0, error = null)
        }
    }

    private suspend fun start() {
        // Новая сессия убирает результат предыдущей отправки с экрана.
        pendingDispatchJob?.cancel()
        pendingDispatchJob = null
        localState.update { it.copy(error = null, sendStatus = SendStatus.Idle, pendingSendSeconds = 0) }
        startRecognition(RecognitionConfig(languageTag = "ru-RU")).onFailure { error ->
            logger.w(TAG, "Не удалось начать распознавание: $error")
            localState.update { it.copy(error = error) }
        }
    }

    /**
     * Отправляет финальный текст на сервер и переводит результат в [SendStatus].
     * Причина сбоя остаётся типизированной ошибкой домена — строку подбирает UI.
     */
    private fun scheduleDispatch(text: String) {
        pendingDispatchJob?.cancel()
        pendingDispatchJob = viewModelScope.launch {
            for (seconds in SEND_DELAY_SECONDS downTo 1) {
                localState.update {
                    it.copy(sendStatus = SendStatus.Pending, pendingSendSeconds = seconds, error = null)
                }
                delay(1_000L)
            }
            dispatchToApi(text)
        }
    }

    private suspend fun dispatchToApi(text: String) {
        localState.update { it.copy(sendStatus = SendStatus.Sending, pendingSendSeconds = 0, error = null) }
        sendText(text)
            .onSuccess {
                logger.i(TAG, "Текст отправлен во внешний сервис")
                localState.update { it.copy(sendStatus = SendStatus.Success) }
            }
            .onFailure { error ->
                logger.w(TAG, "Не удалось отправить текст: $error")
                localState.update { it.copy(sendStatus = SendStatus.Error, pendingSendSeconds = 0, error = error) }
            }
    }

    override fun onCleared() {
        // viewModelScope уже отменён, поэтому освобождаем движок в scope приложения.
        applicationScope.launch {
            cancelRecognition()
            releaseRecognition()
        }
    }

    private fun normalizeRms(rmsDb: Float): Float =
        ((rmsDb - MIN_RMS_DB) / (MAX_RMS_DB - MIN_RMS_DB)).coerceIn(0f, 1f)

    private data class LocalState(
        val error: AppError? = null,
        val sendStatus: SendStatus = SendStatus.Idle,
        val pendingSendSeconds: Int = 0,
        val hasMicrophonePermission: Boolean = false,
    )

    private companion object {
        const val TAG = "MainViewModel"
        const val STATE_TIMEOUT_MILLIS = 5_000L
        const val SEND_DELAY_SECONDS = 3

        /** Диапазон значений RMS, который отдаёт SpeechRecognizer. */
        const val MIN_RMS_DB = -2f
        const val MAX_RMS_DB = 10f
    }
}
