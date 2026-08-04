package com.example.push_to_talk.di

import com.example.push_to_talk.core.dispatcher.DefaultDispatcherProvider
import com.example.push_to_talk.core.dispatcher.DispatcherProvider
import com.example.push_to_talk.core.logger.AndroidLogger
import com.example.push_to_talk.core.logger.Logger
import com.example.push_to_talk.core.permissions.AndroidPermissionChecker
import com.example.push_to_talk.core.permissions.PermissionChecker
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class CoreModule {

    @Binds
    @Singleton
    abstract fun bindLogger(impl: AndroidLogger): Logger

    @Binds
    @Singleton
    abstract fun bindDispatcherProvider(impl: DefaultDispatcherProvider): DispatcherProvider

    @Binds
    @Singleton
    abstract fun bindPermissionChecker(impl: AndroidPermissionChecker): PermissionChecker

    companion object {

        @Provides
        @Singleton
        @ApplicationScope
        fun provideApplicationScope(dispatchers: DispatcherProvider): CoroutineScope =
            CoroutineScope(SupervisorJob() + dispatchers.default)
    }
}
