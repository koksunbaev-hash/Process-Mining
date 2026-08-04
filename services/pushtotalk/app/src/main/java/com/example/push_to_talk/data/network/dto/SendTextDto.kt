package com.example.push_to_talk.data.network.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Тело `POST /api/speech`.
 *
 * Сериализуется в `{"text": "..."}` — ровно то, что ожидает схема `SpeechRequest`
 * на стороне backend-а (`backend/app/schemas/speech.py`).
 */
@Serializable
data class SendTextDto(
    @SerialName("text") val text: String,
)
