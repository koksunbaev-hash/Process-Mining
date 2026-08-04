package com.example.push_to_talk.data.speech

import android.speech.SpeechRecognizer
import com.example.push_to_talk.domain.model.AppError

/** Переводит коды ошибок [SpeechRecognizer] в домен ошибок приложения. */
internal object SpeechErrorMapper {

    fun toAppError(code: Int): AppError.Speech = when (code) {
        SpeechRecognizer.ERROR_AUDIO -> AppError.Speech.MicrophoneUnavailable
        SpeechRecognizer.ERROR_CLIENT -> AppError.Speech.Client
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> AppError.Speech.PermissionDenied
        SpeechRecognizer.ERROR_NETWORK -> AppError.Speech.Network
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> AppError.Speech.NetworkTimeout
        SpeechRecognizer.ERROR_NO_MATCH -> AppError.Speech.NoSpeechDetected
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> AppError.Speech.RecognizerBusy
        SpeechRecognizer.ERROR_SERVER -> AppError.Speech.Server
        SpeechRecognizer.ERROR_SERVER_DISCONNECTED -> AppError.Speech.Server
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> AppError.Speech.SpeechTimeout
        SpeechRecognizer.ERROR_TOO_MANY_REQUESTS -> AppError.Speech.TooManyRequests
        SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED,
        SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE,
        -> AppError.Speech.LanguageUnavailable

        SpeechRecognizer.ERROR_CANNOT_CHECK_SUPPORT -> AppError.Speech.RecognizerUnavailable
        else -> AppError.Speech.Unknown(code)
    }
}
