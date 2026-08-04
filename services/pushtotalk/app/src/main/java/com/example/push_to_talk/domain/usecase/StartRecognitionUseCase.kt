package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.core.permissions.PermissionChecker
import com.example.push_to_talk.core.result.AppResult
import com.example.push_to_talk.core.result.failure
import com.example.push_to_talk.domain.model.AppError
import com.example.push_to_talk.domain.model.RecognitionConfig
import com.example.push_to_talk.domain.repository.SpeechRepository
import javax.inject.Inject

/**
 * Запускает сессию Push-to-Talk: проверяет разрешение, отбрасывает повторные нажатия
 * во время активной сессии и делегирует запуск репозиторию.
 */
class StartRecognitionUseCase @Inject constructor(
    private val speechRepository: SpeechRepository,
    private val permissionChecker: PermissionChecker,
) {
    suspend operator fun invoke(config: RecognitionConfig = RecognitionConfig()): AppResult<Unit> {
        if (!permissionChecker.hasMicrophonePermission()) {
            return failure(AppError.Speech.PermissionDenied)
        }
        if (speechRepository.session.value.isActive) {
            return failure(AppError.Speech.RecognizerBusy)
        }
        return speechRepository.start(config)
    }
}
