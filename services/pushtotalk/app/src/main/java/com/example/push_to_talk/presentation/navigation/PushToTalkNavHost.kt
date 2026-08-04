package com.example.push_to_talk.presentation.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.example.push_to_talk.presentation.main.MainRoute

/** Граф навигации приложения. Новые экраны добавляются сюда без изменения MainActivity. */
@Composable
fun PushToTalkNavHost(
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
            MainRoute()
        }
    }
}
