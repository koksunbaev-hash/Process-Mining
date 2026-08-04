package com.example.push_to_talk.presentation.main

import com.example.push_to_talk.R
import com.example.push_to_talk.domain.model.AppError
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Перевод домена в строковые ресурсы. Значения строк здесь не проверяются —
 * unit-тесты не поднимают ресурсы Android, поэтому сверяются идентификаторы.
 */
class UiMessagesTest {

    @Test
    fun `успех отправки показывает подпись Отправлено`() {
        assertEquals(R.string.send_status_success, SendStatus.Success.messageRes())
    }

    @Test
    fun `ошибка отправки показывает подпись Ошибка отправки`() {
        assertEquals(R.string.send_status_error, SendStatus.Error.messageRes())
    }

    @Test
    fun `идущая отправка показывает прогресс`() {
        assertEquals(R.string.send_status_sending, SendStatus.Sending.messageRes())
    }

    @Test
    fun `до первой отправки подпись отсутствует`() {
        assertNull(SendStatus.Idle.messageRes())
    }

    @Test
    fun `сетевые ошибки различаются на экране`() {
        assertEquals(R.string.error_network_connection, AppError.Network.NoConnection.messageRes())
        assertEquals(R.string.error_network_timeout, AppError.Network.Timeout.messageRes())
        assertEquals(R.string.error_network_http, AppError.Network.Http(400).messageRes())
        assertEquals(R.string.error_network_server, AppError.Network.Server(500).messageRes())
        assertEquals(R.string.error_network_serialization, AppError.Network.Serialization.messageRes())
        assertEquals(R.string.error_network_unexpected, AppError.Network.Unexpected("").messageRes())
    }

    @Test
    fun `пустой текст имеет собственное сообщение`() {
        assertEquals(R.string.error_empty_text, AppError.Validation.EmptyText.messageRes())
    }

    @Test
    fun `у каждой ошибки распознавания есть текст`() {
        val errors = listOf(
            AppError.Speech.RecognizerUnavailable,
            AppError.Speech.MicrophoneUnavailable,
            AppError.Speech.PermissionDenied,
            AppError.Speech.NoSpeechDetected,
            AppError.Speech.SpeechTimeout,
            AppError.Speech.RecognizerBusy,
            AppError.Speech.Cancelled,
            AppError.Speech.Client,
            AppError.Speech.Server,
            AppError.Speech.Network,
            AppError.Speech.NetworkTimeout,
            AppError.Speech.LanguageUnavailable,
            AppError.Speech.TooManyRequests,
            AppError.Speech.Unknown(1),
        )

        errors.forEach { error ->
            assertNotNull("Нет строки для $error", error.messageRes())
        }
    }
}
