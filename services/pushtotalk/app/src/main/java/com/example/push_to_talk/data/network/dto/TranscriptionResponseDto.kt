package com.example.push_to_talk.data.network.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class TranscriptionResponseDto(
    @SerialName("status") val status: String,
    @SerialName("text") val text: String? = null,
    @SerialName("message") val message: String? = null,
) {
    val isAccepted: Boolean get() = status.equals("ok", ignoreCase = true)
}
