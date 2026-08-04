package com.example.push_to_talk.core.permissions

/**
 * Проверка runtime-разрешений без утечки Android-типов в domain- и presentation-слои.
 * Сам запрос разрешения выполняет UI (Activity Result API), здесь только чтение состояния.
 */
interface PermissionChecker {
    fun hasMicrophonePermission(): Boolean
}
