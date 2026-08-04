package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.domain.repository.SpeechRepository
import javax.inject.Inject

/**
 * Останавливает запись и просит движок выдать финальный результат.
 * Используется режимом «удерживай для разговора» при отпускании кнопки.
 */
class StopRecognitionUseCase @Inject constructor(
    private val speechRepository: SpeechRepository,
) {
    suspend operator fun invoke() {
        if (speechRepository.session.value.isActive) {
            speechRepository.stop()
        }
    }
}
