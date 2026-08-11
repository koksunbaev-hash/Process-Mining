package com.example.push_to_talk.data.network.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Body for POST /api/speech. */
@Serializable
data class SendTextDto(
    @SerialName("text") val text: String,
    @SerialName("kms_session_id") val kmsSessionId: String? = null,
)

