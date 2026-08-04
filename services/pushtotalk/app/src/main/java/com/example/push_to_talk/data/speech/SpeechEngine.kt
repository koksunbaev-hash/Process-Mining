package com.example.push_to_talk.data.speech

import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.SpeechEvent
import kotlinx.coroutines.flow.Flow

/**
 * Контракт STT-движка. Текущая реализация — [AndroidSpeechRecognizerEngine];
 * подключение Whisper, Vosk, ML Kit или OpenAI Realtime сводится к новой реализации
 * этого интерфейса и одной строке в Hilt-модуле.
 */
interface SpeechEngine {

    /** Поток событий сессии распознавания. */
    val events: Flow<SpeechEvent>

    /** Доступен ли движок на этом устройстве. */
    fun isAvailable(): Boolean

    /** Запускает сессию распознавания. */
    suspend fun start(config: RecognitionConfig): AppResult<Unit>

    /** Останавливает запись и запрашивает финальный результат. */
    suspend fun stop()

    /** Прерывает сессию без результата. */
    suspend fun cancel()

    /** Освобождает ресурсы движка. */
    suspend fun release()
}
