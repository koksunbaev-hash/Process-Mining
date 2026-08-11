package com.example.push_to_talk.presentation.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.example.push_to_talk.AppLanguage
import com.example.push_to_talk.presentation.main.MainRoute

/** App navigation graph. New screens can be added here without changing MainActivity. */
@Composable
fun PushToTalkNavHost(
    isDarkTheme: Boolean,
    appLanguage: AppLanguage,
    onDarkThemeChange: (Boolean) -> Unit,
    onLanguageChange: (AppLanguage) -> Unit,
    modifier: Modifier = Modifier,
    navController: NavHostController = rememberNavController(),
) {
    val startDestination = remember { MainDestination }
    NavHost(
        navController = navController,
        startDestination = startDestination,
        modifier = modifier,
    ) {
        composable<MainDestination> {
            MainRoute(
                isDarkTheme = isDarkTheme,
                appLanguage = appLanguage,
                onDarkThemeChange = onDarkThemeChange,
                onLanguageChange = onLanguageChange,
            )
        }
    }
}
