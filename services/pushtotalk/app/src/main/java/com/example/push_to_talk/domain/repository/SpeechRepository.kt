package com.example.push_to_talk.domain.repository

import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.model.RecognitionSession
import com.example.push_to_talk.domain.model.SpeechEvent
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

/**
 * Источник распознанной речи для domain-слоя. Реализация скрывает конкретный STT-движок
 * (Android SpeechRecognizer, Whisper, Vosk, ML Kit, OpenAI Realtime и т.д.).
 */
interface SpeechRepository {

    /** Текущее состояние сессии — единственный источник правды для UI. */
    val session: StateFlow<RecognitionSession>

    /** Поток событий для разовых реакций (например, отправка финального текста). */
    val events: Flow<SpeechEvent>

    /** Запускает сессию распознавания. Ошибка возвращается, если сессию начать не удалось. */
    suspend fun start(config: RecognitionConfig): AppResult<Unit>

    /** Останавливает запись и запрашивает финальный результат. */
    suspend fun stop()

    /** Прерывает сессию без результата. */
    suspend fun cancel()

    /** Освобождает ресурсы движка. */
    suspend fun release()
}
