package com.example.push_to_talk.fake

import com.example.push_to_talk.core.dispatcher.DispatcherProvider
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.permissions.PermissionChecker
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.success
import com.example.push_to_talk.data.speech.SpeechEngine
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.RecognitionSession
import com.example.push_to_talk.domain.model.RecognitionStatus
import com.example.push_to_talk.domain.model.SpeechEvent
import com.example.push_to_talk.domain.model.SendTextResult
import com.example.push_to_talk.domain.repository.NetworkRepository
import com.example.push_to_talk.domain.repository.SpeechRepository
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

/** Тестовый STT-источник: сессия и события управляются вручную. */
class FakeSpeechRepository : SpeechRepository {

    private val _session = MutableStateFlow(RecognitionSession())
    override val session: StateFlow<RecognitionSession> = _session.asStateFlow()

    private val _events = MutableSharedFlow<SpeechEvent>(extraBufferCapacity = 16)
    override val events: Flow<SpeechEvent> = _events.asSharedFlow()

    var startResult: AppResult<Unit> = success()
    var startCount = 0
        private set
    var stopCount = 0
        private set
    var cancelCount = 0
        private set
    var releaseCount = 0
        private set
    var lastConfig: RecognitionConfig? = null
        private set

    override suspend fun start(config: RecognitionConfig): AppResult<Unit> {
        startCount++
        lastConfig = config
        // Успешный старт переводит сессию в активное состояние, как в реальном
        // движке: без этого повторное нажатие не отличалось бы от первого.
        if (startResult.isSuccess) {
            setStatus(RecognitionStatus.Listening)
        }
        return startResult
    }

    override suspend fun stop() {
        stopCount++
    }

    override suspend fun cancel() {
        cancelCount++
    }

    override suspend fun release() {
        releaseCount++
    }

    fun setSession(session: RecognitionSession) {
        _session.value = session
    }

    fun setStatus(status: RecognitionStatus) {
        _session.value = _session.value.copy(status = status)
    }

    suspend fun emitEvent(event: SpeechEvent) {
        _events.emit(event)
    }
}

/**
 * Тестовый STT-движок. Позволяет проигрывать произвольную последовательность
 * [SpeechEvent], не поднимая `android.speech.SpeechRecognizer`.
 */
class FakeSpeechEngine : SpeechEngine {

    private val _events = MutableSharedFlow<SpeechEvent>(extraBufferCapacity = 64)
    override val events: Flow<SpeechEvent> = _events.asSharedFlow()

    var available: Boolean = true
    var startResult: AppResult<Unit> = success()
    var startCount = 0
        private set
    var stopCount = 0
        private set
    var cancelCount = 0
        private set
    var releaseCount = 0
        private set

    override fun isAvailable(): Boolean = available

    override suspend fun start(config: RecognitionConfig): AppResult<Unit> {
        startCount++
        return startResult
    }

    override suspend fun stop() {
        stopCount++
    }

    override suspend fun cancel() {
        cancelCount++
    }

    override suspend fun release() {
        releaseCount++
    }

    suspend fun emit(event: SpeechEvent) {
        _events.emit(event)
    }

    /** Проигрывает последовательность событий в порядке поступления. */
    suspend fun emitAll(vararg events: SpeechEvent) {
        events.forEach { emit(it) }
    }
}

/** Тестовый сетевой слой: запоминает отправленные тексты и позволяет задать ошибку. */
class FakeNetworkGateway : NetworkRepository {

    val sentTexts = mutableListOf<String>()
    var result: AppResult<SendTextResult> = success(SendTextResult(accepted = true, forwarded = false, executed = false, commandStatus = null, reason = null))

    /** Сколько раз репозиторий действительно дёрнули. */
    val callCount: Int get() = sentTexts.size

    override suspend fun sendText(text: String): AppResult<SendTextResult> {
        sentTexts += text
        return result
    }
}

class FakePermissionChecker(var granted: Boolean = true) : PermissionChecker {
    override fun hasMicrophonePermission(): Boolean = granted
}

class FakeLogger : Logger {
    override fun d(tag: String, message: String) = Unit
    override fun i(tag: String, message: String) = Unit
    override fun w(tag: String, message: String, throwable: Throwable?) = Unit
    override fun e(tag: String, message: String, throwable: Throwable?) = Unit
}

/** Все диспетчеры сведены к одному тестовому — выполнение остаётся детерминированным. */
class TestDispatcherProvider(dispatcher: CoroutineDispatcher) : DispatcherProvider {
    override val main: CoroutineDispatcher = dispatcher
    override val mainImmediate: CoroutineDispatcher = dispatcher
    override val io: CoroutineDispatcher = dispatcher
    override val default: CoroutineDispatcher = dispatcher
}

/** Удобное сравнение ошибок в тестах. */
fun AppResult<*>.errorOrFail(): AppError =
    errorOrNull() ?: error("Ожидалась ошибка, получен успешный результат")
