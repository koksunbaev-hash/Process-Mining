package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.SendTextResult
import com.example.push_to_talk.domain.repository.NetworkRepository
import javax.inject.Inject

/**
 * Отправляет распознанный текст во внешний сервис.
 * Валидация выполняется здесь, чтобы пустые реплики не доходили до сети.
 */
class SendTextUseCase @Inject constructor(
    private val networkRepository: NetworkRepository,
) {
    suspend operator fun invoke(text: String): AppResult<SendTextResult> {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) {
            return failure(AppError.Validation.EmptyText)
        }
        return networkRepository.sendText(trimmed)
    }
}
