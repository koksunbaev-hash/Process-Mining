package com.example.push_to_talk.data.repository

import com.example.push_to_talk.core.dispatcher.DispatcherProvider
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.core.result.success
import com.example.push_to_talk.data.auth.KmsSessionProvider
import com.example.push_to_talk.data.network.ApiService
import com.example.push_to_talk.data.network.NetworkErrorMapper
import com.example.push_to_talk.data.network.dto.SendTextDto
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.SendTextResult
import com.example.push_to_talk.domain.repository.NetworkRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

/** Production Retrofit-backed implementation of NetworkRepository. */
@Singleton
class RetrofitNetworkRepository @Inject constructor(
    private val apiService: ApiService,
    private val dispatchers: DispatcherProvider,
    private val logger: Logger,
    private val kmsSessionProvider: KmsSessionProvider,
) : NetworkRepository {

    override suspend fun sendText(text: String): AppResult<SendTextResult> {
        val payload = text.trim()
        if (payload.isEmpty()) {
            logger.w(TAG, "РџСѓСЃС‚РѕР№ С‚РµРєСЃС‚ РЅРµ РѕС‚РїСЂР°РІР»СЏРµС‚СЃСЏ")
            return failure(AppError.Validation.EmptyText)
        }

        return withContext(dispatchers.io) {
            try {
                val response = apiService.sendText(
                    SendTextDto(
                        text = payload,
                        kmsSessionId = kmsSessionProvider.currentSessionId(),
                    )
                )
                if (!response.isAccepted) {
                    logger.w(TAG, "РЎРµСЂРІРµСЂ РѕС‚РІРµС‚РёР» СЃС‚Р°С‚СѓСЃРѕРј \"${response.status}\"")
                }
                logger.i(TAG, "РўРµРєСЃС‚ РїСЂРёРЅСЏС‚ СЃРµСЂРІРµСЂРѕРј, id=${response.id}")
                success(
                    SendTextResult(
                        accepted = response.isAccepted,
                        forwarded = response.forwarded,
                        executed = response.executed,
                        commandStatus = response.commandStatus,
                        reason = response.reason ?: response.message,
                    )
                )
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (throwable: Throwable) {
                val error = NetworkErrorMapper.toAppError(throwable)
                logger.e(TAG, "РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РїСЂР°РІРёС‚СЊ С‚РµРєСЃС‚: $error", throwable)
                failure(error)
            }
        }
    }

    private companion object {
        const val TAG = "RetrofitNetwork"
    }
}
