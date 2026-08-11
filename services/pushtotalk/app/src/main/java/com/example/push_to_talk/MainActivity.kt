package com.example.push_to_talk

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.example.push_to_talk.data.auth.KmsAuthClient
import com.example.push_to_talk.presentation.auth.LoginScreen
import com.example.push_to_talk.presentation.navigation.PushToTalkNavHost
import com.example.push_to_talk.ui.theme.PushtotalkTheme
import dagger.hilt.android.AndroidEntryPoint

enum class AppLanguage(val tag: String) {
    Kk("kk-KZ"),
    Ru("ru"),
}

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val authPreferences = getSharedPreferences(AUTH_PREFS, Context.MODE_PRIVATE)

        setContent {
            var isDarkTheme by rememberSaveable { androidx.compose.runtime.mutableStateOf(false) }
            var appLanguage by rememberSaveable { androidx.compose.runtime.mutableStateOf(AppLanguage.Ru) }
            var isAuthenticated by rememberSaveable {
                androidx.compose.runtime.mutableStateOf(
                    authPreferences.getBoolean(KEY_AUTHENTICATED, false),
                )
            }
            var username by rememberSaveable {
                androidx.compose.runtime.mutableStateOf(authPreferences.getString(KEY_USERNAME, "").orEmpty())
            }
            val authClient = remember { KmsAuthClient(BuildConfig.KMS_BASE_URL) }

            PushtotalkTheme(darkTheme = isDarkTheme) {
                if (isAuthenticated) {
                    PushToTalkNavHost(
                        username = username,
                        isDarkTheme = isDarkTheme,
                        appLanguage = appLanguage,
                        onDarkThemeChange = { isDarkTheme = it },
                        onLanguageChange = { appLanguage = it },
                        onLogout = {
                            authPreferences.edit().clear().apply()
                            username = ""
                            isAuthenticated = false
                        },
                    )
                } else {
                    LoginScreen(
                        appLanguage = appLanguage,
                        onLogin = { loginUsername, password ->
                            val success = authClient.login(loginUsername, password)
                            if (success) {
                                authPreferences.edit()
                                    .putBoolean(KEY_AUTHENTICATED, true)
                                    .putString(KEY_USERNAME, loginUsername)
                                    .apply()
                                username = loginUsername
                                isAuthenticated = true
                            }
                            success
                        },
                    )
                }
            }
        }
    }

    private companion object {
        const val AUTH_PREFS = "kms_auth"
        const val KEY_AUTHENTICATED = "authenticated"
        const val KEY_USERNAME = "username"
    }
}
