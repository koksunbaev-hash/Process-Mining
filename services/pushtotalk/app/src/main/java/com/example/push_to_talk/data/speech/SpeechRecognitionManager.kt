package com.example.push_to_talk.data.speech

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import com.example.push_to_talk.core.dispatcher.DispatcherProvider
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.core.result.success
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.SpeechEvent
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Единственное место в приложении, которое знает про [SpeechRecognizer].
 *
 * Правила платформы, которые здесь соблюдаются:
 * - все вызовы API распознавателя выполняются в главном потоке;
 * - распознаватель рассчитан на отдельные короткие сессии, а не на непрерывное слушание;
 * - ресурсы освобождаются через [SpeechRecognizer.destroy] в [release].
 *
 * Наружу отдаются только события [SpeechEvent] — callback-ов за пределами этого класса нет.
 */
@Singleton
class SpeechRecognitionManager @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val dispatchers: DispatcherProvider,
    private val logger: Logger,
) {
    private val scope = CoroutineScope(SupervisorJob() + dispatchers.mainImmediate)

    private val _events = MutableSharedFlow<SpeechEvent>(
        extraBufferCapacity = EVENT_BUFFER_CAPACITY,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val events: SharedFlow<SpeechEvent> = _events.asSharedFlow()

    /** Все поля ниже читаются и пишутся только в главном потоке. */
    private var recognizer: SpeechRecognizer? = null
    private var isSessionActive = false
    private var isCancelling = false
    private var watchdogJob: Job? = null

    private val listener = object : RecognitionListener {

        override fun onReadyForSpeech(params: Bundle?) {
            emit(SpeechEvent.ReadyForSpeech)
        }

        override fun onBeginningOfSpeech() {
            cancelWatchdog()
            emit(SpeechEvent.SpeechStarted)
        }

        override fun onRmsChanged(rmsdB: Float) {
            emit(SpeechEvent.RmsChanged(rmsdB))
        }

        override fun onBufferReceived(buffer: ByteArray?) = Unit

        override fun onEndOfSpeech() {
            cancelWatchdog()
            emit(SpeechEvent.SpeechEnded)
        }

        override fun onError(error: Int) {
            finishSession()
            if (isCancelling) {
                isCancelling = false
                logger.d(TAG, "Ошибка $error после отмены сессии — игнорируем")
                return
            }
            val appError = SpeechErrorMapper.toAppError(error)
            logger.w(TAG, "Сессия завершилась ошибкой: $appError")
            emit(SpeechEvent.Failed(appError))
        }

        override fun onResults(results: Bundle?) {
            finishSession()
            isCancelling = false
            val text = results.firstRecognizedText()
            if (text.isEmpty()) {
                emit(SpeechEvent.Failed(AppError.Speech.NoSpeechDetected))
            } else {
                emit(SpeechEvent.FinalResult(text))
            }
        }

        override fun onPartialResults(partialResults: Bundle?) {
            val text = partialResults.firstRecognizedText()
            if (text.isNotEmpty()) {
                emit(SpeechEvent.PartialResult(text))
            }
        }

        override fun onEvent(eventType: Int, params: Bundle?) = Unit
    }

    fun isAvailable(): Boolean = SpeechRecognizer.isRecognitionAvailable(context)

    suspend fun start(config: RecognitionConfig): AppResult<Unit> =
        withContext(dispatchers.mainImmediate) {
            if (!isAvailable()) {
                logger.w(TAG, "На устройстве нет сервиса распознавания речи")
                emit(SpeechEvent.Failed(AppError.Speech.RecognizerUnavailable))
                return@withContext failure(AppError.Speech.RecognizerUnavailable)
            }
            if (isSessionActive) {
                return@withContext failure(AppError.Speech.RecognizerBusy)
            }

            isSessionActive = true
            isCancelling = false
            emit(SpeechEvent.Preparing)

            val activeRecognizer = recognizer ?: createRecognizer().also { recognizer = it }
            runCatching { activeRecognizer.startListening(buildIntent(config)) }.fold(
                onSuccess = {
                    startWatchdog(config.speechInputTimeoutMillis)
                    success()
                },
                onFailure = { throwable ->
                    logger.e(TAG, "Не удалось запустить распознавание", throwable)
                    finishSession()
                    emit(SpeechEvent.Failed(AppError.Speech.Client))
                    failure(AppError.Speech.Client)
                },
            )
        }

    suspend fun stop() = withContext(dispatchers.mainImmediate) {
        if (!isSessionActive) return@withContext
        cancelWatchdog()
        logger.d(TAG, "Останавливаем запись, ждём финальный результат")
        recognizer?.stopListening()
    }

    suspend fun cancel() = withContext(dispatchers.mainImmediate) {
        if (!isSessionActive) return@withContext
        isCancelling = true
        finishSession()
        recognizer?.cancel()
        emit(SpeechEvent.Cancelled)
    }

    suspend fun release() = withContext(dispatchers.mainImmediate) {
        finishSession()
        isCancelling = false
        recognizer?.destroy()
        recognizer = null
        logger.d(TAG, "Ресурсы распознавателя освобождены")
    }

    private fun createRecognizer(): SpeechRecognizer =
        SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(listener)
        }

    private fun buildIntent(config: RecognitionConfig): Intent =
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
            )
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, config.partialResults)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, MAX_RESULTS)
            putExtra(
                RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS,
                config.silenceTimeoutMillis,
            )
            putExtra(
                RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS,
                config.silenceTimeoutMillis,
            )
            putExtra(
                RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS,
                config.minimumSpeechLengthMillis,
            )
            config.languageTag?.let { putExtra(RecognizerIntent.EXTRA_LANGUAGE, it) }
            if (config.preferOffline) {
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            }
        }

    /**
     * Страховка от «молчаливых» реализаций RecognitionService: если движок не сообщил
     * о начале речи за отведённое время, сессия закрывается по таймауту.
     */
    private fun startWatchdog(timeoutMillis: Long) {
        watchdogJob?.cancel()
        watchdogJob = scope.launch {
            delay(timeoutMillis + WATCHDOG_GRACE_MILLIS)
            if (isSessionActive) {
                logger.w(TAG, "Движок не ответил за ${timeoutMillis}мс — закрываем сессию")
                isCancelling = true
                finishSession()
                recognizer?.cancel()
                emit(SpeechEvent.Failed(AppError.Speech.SpeechTimeout))
            }
        }
    }

    private fun cancelWatchdog() {
        watchdogJob?.cancel()
        watchdogJob = null
    }

    private fun finishSession() {
        cancelWatchdog()
        isSessionActive = false
    }

    private fun emit(event: SpeechEvent) {
        if (!_events.tryEmit(event)) {
            logger.w(TAG, "Буфер событий переполнен, событие потеряно: $event")
        }
    }

    private fun Bundle?.firstRecognizedText(): String =
        this?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull()
            ?.trim()
            .orEmpty()

    private companion object {
        const val TAG = "SpeechManager"
        const val MAX_RESULTS = 1
        const val EVENT_BUFFER_CAPACITY = 64
        const val WATCHDOG_GRACE_MILLIS = 2_000L
    }
}
