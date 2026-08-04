package com.example.push_to_talk.domain.model

/**
 * События одной сессии распознавания. Это единственный способ, которым движок распознавания
 * сообщает наружу о происходящем: никаких callback-ов за пределами data-слоя.
 */
sealed interface SpeechEvent {

    /** Сессия создаётся: движок инициализируется, аудио ещё не пишется. */
    data object Preparing : SpeechEvent

    /** Движок готов принимать речь. */
    data object ReadyForSpeech : SpeechEvent

    /** Движок определил начало речи. */
    data object SpeechStarted : SpeechEvent

    /** Движок определил конец речи, запись остановлена. */
    data object SpeechEnded : SpeechEvent

    /** Текущий уровень входного сигнала в dB, для индикации в UI. */
    data class RmsChanged(val rmsDb: Float) : SpeechEvent

    /** Промежуточный результат распознавания. */
    data class PartialResult(val text: String) : SpeechEvent

    /** Финальный результат распознавания. */
    data class FinalResult(val text: String) : SpeechEvent

    /** Сессия отменена. */
    data object Cancelled : SpeechEvent

    /** Сессия завершилась ошибкой. */
    data class Failed(val error: AppError.Speech) : SpeechEvent
}
