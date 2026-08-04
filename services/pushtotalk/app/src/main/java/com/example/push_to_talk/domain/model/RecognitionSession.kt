package com.example.push_to_talk.domain.model

/** Жизненный цикл одной сессии Push-to-Talk. */
enum class RecognitionStatus {
    Idle,
    Preparing,
    Listening,
    SpeechDetected,
    Recognizing,
    Success,
    Error,
}

/**
 * Единственный источник правды о текущей сессии распознавания.
 * Состояние собирается из потока [SpeechEvent] в data-слое и только читается остальными слоями.
 */
data class RecognitionSession(
    val status: RecognitionStatus = RecognitionStatus.Idle,
    val partialText: String = "",
    val finalText: String = "",
    val rmsDb: Float = 0f,
    val error: AppError.Speech? = null,
) {
    /** Текст, который имеет смысл показывать пользователю прямо сейчас. */
    val displayText: String get() = finalText.ifBlank { partialText }

    /** Идёт запись аудио. */
    val isListening: Boolean
        get() = status == RecognitionStatus.Listening || status == RecognitionStatus.SpeechDetected

    /** Сессия занята: новую начинать нельзя. */
    val isActive: Boolean
        get() = status == RecognitionStatus.Preparing ||
            status == RecognitionStatus.Listening ||
            status == RecognitionStatus.SpeechDetected ||
            status == RecognitionStatus.Recognizing
}
