package com.example.push_to_talk.data.repository

import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.success
import com.example.push_to_talk.domain.model.SendTextResult
import com.example.push_to_talk.domain.repository.NetworkRepository
import kotlinx.coroutines.delay
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Заглушка на время отсутствия сервера: имитирует сетевую задержку и логирует полезную нагрузку.
 * Заменяется на [RetrofitNetworkRepository] одной строкой в
 * [com.example.push_to_talk.di.RepositoryModule].
 */
@Singleton
class FakeNetworkRepository @Inject constructor(
    private val logger: Logger,
) : NetworkRepository {

    override suspend fun sendText(text: String): AppResult<SendTextResult> {
        logger.i(TAG, "Отправка текста в заглушку API: \"$text\"")
        delay(FAKE_LATENCY_MILLIS)
        return success(SendTextResult(accepted = true, forwarded = false, executed = false, commandStatus = null, reason = null))
    }

    private companion object {
        const val TAG = "FakeNetwork"
        const val FAKE_LATENCY_MILLIS = 300L
    }
}
