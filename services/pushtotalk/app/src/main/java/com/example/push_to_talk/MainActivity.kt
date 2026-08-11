package com.example.push_to_talk

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
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
        setContent {
            var isDarkTheme by rememberSaveable { androidx.compose.runtime.mutableStateOf(false) }
            var appLanguage by rememberSaveable { androidx.compose.runtime.mutableStateOf(AppLanguage.Ru) }

            PushtotalkTheme(darkTheme = isDarkTheme) {
                PushToTalkNavHost(
                    isDarkTheme = isDarkTheme,
                    appLanguage = appLanguage,
                    onDarkThemeChange = { isDarkTheme = it },
                    onLanguageChange = { appLanguage = it },
                )
            }
        }
    }
}




