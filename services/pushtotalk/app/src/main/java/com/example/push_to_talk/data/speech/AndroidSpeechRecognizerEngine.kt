package com.example.push_to_talk.data.speech

import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.SpeechEvent
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Реализация [SpeechEngine] поверх системного распознавателя Android.
 * Вся работа с платформой инкапсулирована в [SpeechRecognitionManager].
 */
@Singleton
class AndroidSpeechRecognizerEngine @Inject constructor(
    private val manager: SpeechRecognitionManager,
) : SpeechEngine {

    override val events: Flow<SpeechEvent> = manager.events

    override fun isAvailable(): Boolean = manager.isAvailable()

    override suspend fun start(config: RecognitionConfig): AppResult<Unit> = manager.start(config)

    override suspend fun stop() = manager.stop()

    override suspend fun cancel() = manager.cancel()

    override suspend fun release() = manager.release()
}
