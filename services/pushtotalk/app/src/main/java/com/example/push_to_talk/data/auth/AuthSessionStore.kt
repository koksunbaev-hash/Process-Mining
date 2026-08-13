package com.example.push_to_talk.data.auth

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

object AuthSessionKeys {
    const val PREFS = "kms_auth"
    const val AUTHENTICATED = "authenticated"
    const val USERNAME = "username"
    const val KMS_COOKIES = "kms_cookies"
}

fun interface KmsSessionProvider {
    fun currentSessionId(): String?
}

@Singleton
class SharedPrefsKmsSessionProvider @Inject constructor(
    @ApplicationContext context: Context,
) : KmsSessionProvider {
    private val preferences = context.getSharedPreferences(AuthSessionKeys.PREFS, Context.MODE_PRIVATE)

    override fun currentSessionId(): String? =
        preferences.getString(AuthSessionKeys.KMS_COOKIES, null)
            ?.lineSequence()
            ?.map { it.substringBefore(';').trim() }
            ?.firstOrNull { it.startsWith("sessionid=") }
            ?.substringAfter("sessionid=")
            ?.takeIf { it.isNotBlank() }
}
