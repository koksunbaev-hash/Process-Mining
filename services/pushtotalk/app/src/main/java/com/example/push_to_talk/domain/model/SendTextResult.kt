package com.example.push_to_talk.domain.model

data class SendTextResult(
    val accepted: Boolean,
    val forwarded: Boolean,
    val executed: Boolean,
    val commandStatus: String?,
    val reason: String?,
)
