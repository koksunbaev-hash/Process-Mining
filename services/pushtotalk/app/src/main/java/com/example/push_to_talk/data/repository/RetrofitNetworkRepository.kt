package com.example.push_to_talk.data.repository

import com.example.push_to_talk.core.dispatcher.DispatcherProvider
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.core.result.success
import com.example.push_to_talk.data.network.ApiService
import com.example.push_to_talk.data.network.NetworkErrorMapper
import com.example.push_to_talk.data.network.dto.SendTextDto
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.repository.NetworkRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Боевая реализация [NetworkRepository] поверх Retrofit.
 *
 * Наружу не выходит ни одного исключения: любой сбой превращается в
 * [AppResult.Failure] с типизированной [AppError], поэтому use case-ы и
 * ViewModel не знают ни про Retrofit, ни про HTTP-коды.
 */
@Singleton
class RetrofitNetworkRepository @Inject constructor(
    private val apiService: ApiService,
    private val dispatchers: DispatcherProvider,
    private val logger: Logger,
) : NetworkRepository {

    override suspend fun sendText(text: String): AppResult<Unit> {
        // Страховка на случай вызова в обход SendTextUseCase: пустой текст
        // не должен занимать сеть и создавать мусорные записи на сервере.
        val payload = text.trim()
        if (payload.isEmpty()) {
            logger.w(TAG, "Пустой текст не отправляется")
            return failure(AppError.Validation.EmptyText)
        }

        return withContext(dispatchers.io) {
            try {
                val response = apiService.sendText(SendTextDto(text = payload))
                if (!response.isAccepted) {
                    // HTTP 2xx с чужим статусом: контракт разошёлся, но сеть исправна.
                    logger.w(TAG, "Сервер ответил статусом \"${response.status}\"")
                }
                logger.i(TAG, "Текст принят сервером, id=${response.id}")
                success()
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (throwable: Throwable) {
                val error = NetworkErrorMapper.toAppError(throwable)
                logger.e(TAG, "Не удалось отправить текст: $error", throwable)
                failure(error)
            }
        }
    }

    private companion object {
        const val TAG = "RetrofitNetwork"
    }
}
