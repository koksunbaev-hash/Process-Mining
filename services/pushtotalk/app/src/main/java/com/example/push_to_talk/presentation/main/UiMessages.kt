package com.example.push_to_talk.presentation.main

import androidx.annotation.StringRes
import com.example.push_to_talk.R
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionStatus

/** Перевод статуса сессии в подпись на экране. */
@StringRes
internal fun RecognitionStatus.labelRes(): Int = when (this) {
    RecognitionStatus.Idle -> R.string.status_idle
    RecognitionStatus.Preparing -> R.string.status_preparing
    RecognitionStatus.Listening -> R.string.status_listening
    RecognitionStatus.SpeechDetected -> R.string.status_speech_detected
    RecognitionStatus.Recognizing -> R.string.status_recognizing
    RecognitionStatus.Success -> R.string.status_success
    RecognitionStatus.Error -> R.string.status_error
}

/**
 * Перевод результата отправки в подпись на экране.
 *
 * `null` означает «показывать нечего»: отправок ещё не было.
 */
internal fun SendStatus.messageRes(): Int? = when (this) {
    SendStatus.Idle -> null
    SendStatus.Sending -> R.string.send_status_sending
    SendStatus.Success -> R.string.send_status_success
    SendStatus.Error -> R.string.send_status_error
}

/** Перевод типизированной ошибки в текст для пользователя. */
@StringRes
internal fun AppError.messageRes(): Int = when (this) {
    AppError.Speech.RecognizerUnavailable -> R.string.error_recognizer_unavailable
    AppError.Speech.MicrophoneUnavailable -> R.string.error_microphone_unavailable
    AppError.Speech.PermissionDenied -> R.string.error_permission_denied
    AppError.Speech.NoSpeechDetected -> R.string.error_no_speech
    AppError.Speech.SpeechTimeout -> R.string.error_speech_timeout
    AppError.Speech.RecognizerBusy -> R.string.error_recognizer_busy
    AppError.Speech.Cancelled -> R.string.error_cancelled
    AppError.Speech.Client -> R.string.error_speech_client
    AppError.Speech.Server -> R.string.error_speech_server
    AppError.Speech.Network -> R.string.error_network_connection
    AppError.Speech.NetworkTimeout -> R.string.error_network_timeout
    AppError.Speech.LanguageUnavailable -> R.string.error_language_unavailable
    AppError.Speech.TooManyRequests -> R.string.error_too_many_requests
    is AppError.Speech.Unknown -> R.string.error_speech_unknown
    AppError.Network.NoConnection -> R.string.error_network_connection
    AppError.Network.Timeout -> R.string.error_network_timeout
    is AppError.Network.Http -> R.string.error_network_http
    is AppError.Network.Server -> R.string.error_network_server
    AppError.Network.Serialization -> R.string.error_network_serialization
    is AppError.Network.Unexpected -> R.string.error_network_unexpected
    AppError.Validation.EmptyText -> R.string.error_empty_text
}
