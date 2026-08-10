package com.example.push_to_talk.domain.repository

import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.domain.model.SendTextResult

/** Отправка распознанного текста во внешний сервис. */
interface NetworkRepository {
    suspend fun sendText(text: String): AppResult<SendTextResult>
}
