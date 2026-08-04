package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.domain.repository.SpeechRepository
import javax.inject.Inject

/** Прерывает текущую сессию без получения результата. */
class CancelRecognitionUseCase @Inject constructor(
    private val speechRepository: SpeechRepository,
) {
    suspend operator fun invoke() {
        speechRepository.cancel()
    }
}
