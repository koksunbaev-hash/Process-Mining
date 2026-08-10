package com.example.push_to_talk.data.network.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

private const val STATUS_OK = "ok"

/**
 * Ответ `POST /api/speech`.
 *
 * Успех: `{"status": "ok", "id": 1}`.
 * Ошибка приходит с кодом 4xx/5xx и телом `{"status": "error", "message": "..."}`,
 * поэтому [message] опционален — при успехе сервер его не присылает.
 *
 * Константа вынесена на уровень файла осознанно: `private companion object`
 * внутри `@Serializable`-класса делает сгенерированный `serializer()`
 * недоступным для рефлексии, и разбор ответа падает в рантайме.
 */
@Serializable
data class SendTextResponseDto(
    @SerialName("status") val status: String,
    @SerialName("id") val id: Int? = null,
    @SerialName("message") val message: String? = null,
    @SerialName("forwarded") val forwarded: Boolean = false,
    @SerialName("executed") val executed: Boolean = false,
    @SerialName("command_status") val commandStatus: String? = null,
    @SerialName("reason") val reason: String? = null,
) {
    /** Сервер подтвердил приём. */
    val isAccepted: Boolean get() = status.equals(STATUS_OK, ignoreCase = true)
}
