package com.example.push_to_talk.domain.usecase

import com.example.push_to_talk.core.permissions.PermissionChecker
import javax.inject.Inject

/** Проверяет, выдано ли разрешение на запись аудио. */
class CheckMicrophonePermissionUseCase @Inject constructor(
    private val permissionChecker: PermissionChecker,
) {
    operator fun invoke(): Boolean = permissionChecker.hasMicrophonePermission()
}
