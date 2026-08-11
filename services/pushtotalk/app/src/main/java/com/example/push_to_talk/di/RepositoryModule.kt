package com.example.push_to_talk.di

import com.example.push_to_talk.data.auth.KmsSessionProvider
import com.example.push_to_talk.data.auth.SharedPrefsKmsSessionProvider
import com.example.push_to_talk.data.repository.RetrofitNetworkRepository
import com.example.push_to_talk.data.repository.SpeechRepositoryImpl
import com.example.push_to_talk.data.speech.RemoteWhisperSpeechEngine
import com.example.push_to_talk.data.speech.SpeechEngine
import com.example.push_to_talk.domain.repository.NetworkRepository
import com.example.push_to_talk.domain.repository.SpeechRepository
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {

    @Binds
    @Singleton
    abstract fun bindSpeechEngine(impl: RemoteWhisperSpeechEngine): SpeechEngine

    @Binds
    @Singleton
    abstract fun bindSpeechRepository(impl: SpeechRepositoryImpl): SpeechRepository

    @Binds
    @Singleton
    abstract fun bindNetworkRepository(impl: RetrofitNetworkRepository): NetworkRepository

    @Binds
    @Singleton
    abstract fun bindKmsSessionProvider(impl: SharedPrefsKmsSessionProvider): KmsSessionProvider
}