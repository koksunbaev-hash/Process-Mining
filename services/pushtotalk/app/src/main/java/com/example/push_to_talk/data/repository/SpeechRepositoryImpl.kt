package com.example.push_to_talk.data.repository

import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.data.speech.SpeechEngine
import com.example.push_to_talk.di.ApplicationScope
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.RecognitionSession
import com.example.push_to_talk.domain.model.RecognitionStatus
import com.example.push_to_talk.domain.model.SpeechEvent
import com.example.push_to_talk.domain.repository.SpeechRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.scan
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Сворачивает поток событий движка в состояние сессии.
 * Состояние собирается ровно в одном месте, поэтому UI и domain читают один источник правды.
 */
@Singleton
class SpeechRepositoryImpl @Inject constructor(
    private val engine: SpeechEngine,
    @param:ApplicationScope private val scope: CoroutineScope,
    private val logger: Logger,
) : SpeechRepository {

    override val events: Flow<SpeechEvent> = engine.events

    override val session: StateFlow<RecognitionSession> = engine.events
        .onEach { logger.d(TAG, "Событие: $it") }
        .scan(RecognitionSession()) { current, event -> current.reduce(event) }
        // Eagerly: события движка — «горячий» поток без replay, подписка должна жить
        // всё время работы приложения, иначе первые события сессии будут потеряны.
        .stateIn(scope, SharingStarted.Eagerly, RecognitionSession())

    override suspend fun start(config: RecognitionConfig): AppResult<Unit> = engine.start(config)

    override suspend fun stop() = engine.stop()

    override suspend fun cancel() = engine.cancel()

    override suspend fun release() = engine.release()

    private companion object {
        const val TAG = "SpeechRepository"
    }
}

private fun RecognitionSession.reduce(event: SpeechEvent): RecognitionSession = when (event) {
    SpeechEvent.Preparing -> RecognitionSession(status = RecognitionStatus.Preparing)

    SpeechEvent.ReadyForSpeech -> copy(status = RecognitionStatus.Listening)

    SpeechEvent.SpeechStarted -> copy(status = RecognitionStatus.SpeechDetected)

    SpeechEvent.SpeechEnded -> copy(status = RecognitionStatus.Recognizing, rmsDb = 0f)

    is SpeechEvent.RmsChanged -> copy(rmsDb = event.rmsDb)

    is SpeechEvent.PartialResult -> copy(partialText = event.text)

    is SpeechEvent.FinalResult -> copy(
        status = RecognitionStatus.Success,
        partialText = "",
        finalText = event.text,
        rmsDb = 0f,
        error = null,
    )

    SpeechEvent.Cancelled -> RecognitionSession(finalText = finalText)

    is SpeechEvent.Failed -> copy(
        status = RecognitionStatus.Error,
        partialText = "",
        rmsDb = 0f,
        error = event.error,
    )
}
