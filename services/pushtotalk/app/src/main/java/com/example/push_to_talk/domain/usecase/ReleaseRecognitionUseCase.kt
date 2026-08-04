package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.domain.repository.SpeechRepository
import javax.inject.Inject

/** Освобождает ресурсы движка распознавания при завершении работы экрана. */
class ReleaseRecognitionUseCase @Inject constructor(
    private val speechRepository: SpeechRepository,
) {
    suspend operator fun invoke() {
        speechRepository.release()
    }
}
