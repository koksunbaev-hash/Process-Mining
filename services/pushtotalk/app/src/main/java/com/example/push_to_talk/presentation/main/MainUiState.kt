package com.example.push_to_talk.presentation.main

import androidx.compose.runtime.Immutable
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionStatus

/**
 * Неизменяемое состояние экрана. Полностью выводится из состояния сессии распознавания
 * и локальных флагов ViewModel — UI не хранит собственного состояния.
 */
@Immutable
data class MainUiState(
    val status: RecognitionStatus = RecognitionStatus.Idle,
    val recognizedText: String = "",
    val isListening: Boolean = false,
    val isSessionActive: Boolean = false,
    val hasMicrophonePermission: Boolean = false,
    /** Нормализованный уровень сигнала 0..1 для индикации вокруг кнопки. */
    val audioLevel: Float = 0f,
    /** Чем закончилась последняя попытка отправки текста на сервер. */
    val sendStatus: SendStatus = SendStatus.Idle,
    val sendDetail: String? = null,
    val pendingSendSeconds: Int = 0,
    val error: AppError? = null,
) {
    /** Идёт запрос к серверу: кнопка заблокирована, показан индикатор. */
    val isSending: Boolean get() = sendStatus == SendStatus.Sending
}

/**
 * Результат отправки распознанного текста.
 *
 * Domain об этом не знает: он возвращает [AppResult], а превращение результата
 * в подпись на экране живёт в `UiMessages.kt`.
 *
 * @see com.example.push_to_talk.core.result.AppResult
 */
enum class SendStatus {
    /** Отправок ещё не было либо результат уже показан и сброшен. */
    Idle,

    /** Текст распознан и ждёт короткое окно отмены перед отправкой. */
    Pending,

    /** Запрос ушёл, ответа ещё нет. */
    Sending,

    /** Сервер подтвердил приём. */
    Success,

    CommandRejected,

    /** Пользователь отменил отправку распознанного текста. */
    Cancelled,

    /** Отправить не удалось; причина лежит в [MainUiState.error]. */
    Error,
}

/** Режим работы кнопки. Смена режима не затрагивает бизнес-логику. */
enum class PushToTalkMode {
    /** Нажатие запускает сессию, повторное нажатие — останавливает. */
    Tap,

    /** Сессия идёт, пока кнопка удерживается. */
    Hold,
}
