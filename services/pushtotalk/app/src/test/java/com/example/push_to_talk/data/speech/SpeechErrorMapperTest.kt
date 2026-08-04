package com.example.push_to_talk.data.speech

import android.speech.SpeechRecognizer
import com.example.push_to_talk.domain.model.AppError
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Коды `SpeechRecognizer` — константы времени компиляции, поэтому тест
 * не поднимает Android-платформу.
 */
class SpeechErrorMapperTest {

    @Test
    fun `ERROR_AUDIO означает недоступный микрофон`() {
        assertEquals(
            AppError.Speech.MicrophoneUnavailable,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_AUDIO),
        )
    }

    @Test
    fun `ERROR_SPEECH_TIMEOUT означает таймаут речи`() {
        assertEquals(
            AppError.Speech.SpeechTimeout,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_SPEECH_TIMEOUT),
        )
    }

    @Test
    fun `ERROR_INSUFFICIENT_PERMISSIONS означает отсутствие разрешения`() {
        assertEquals(
            AppError.Speech.PermissionDenied,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS),
        )
    }

    @Test
    fun `ERROR_NO_MATCH означает нераспознанную речь`() {
        assertEquals(
            AppError.Speech.NoSpeechDetected,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_NO_MATCH),
        )
    }

    @Test
    fun `ERROR_RECOGNIZER_BUSY означает занятость движка`() {
        assertEquals(
            AppError.Speech.RecognizerBusy,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_RECOGNIZER_BUSY),
        )
    }

    @Test
    fun `ERROR_NETWORK и ERROR_NETWORK_TIMEOUT различаются`() {
        assertEquals(
            AppError.Speech.Network,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_NETWORK),
        )
        assertEquals(
            AppError.Speech.NetworkTimeout,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_NETWORK_TIMEOUT),
        )
    }

    @Test
    fun `оба кода языка сводятся к недоступному языку`() {
        assertEquals(
            AppError.Speech.LanguageUnavailable,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED),
        )
        assertEquals(
            AppError.Speech.LanguageUnavailable,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE),
        )
    }

    @Test
    fun `оба серверных кода сводятся к ошибке сервиса`() {
        assertEquals(
            AppError.Speech.Server,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_SERVER),
        )
        assertEquals(
            AppError.Speech.Server,
            SpeechErrorMapper.toAppError(SpeechRecognizer.ERROR_SERVER_DISCONNECTED),
        )
    }

    @Test
    fun `неизвестный код сохраняется как есть`() {
        assertEquals(AppError.Speech.Unknown(9999), SpeechErrorMapper.toAppError(9999))
    }
}
