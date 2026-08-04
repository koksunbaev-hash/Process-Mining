package com.example.push_to_talk.di

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

/**
 * Точка подмены реализаций. Смена STT-движка или включение реального API
 * не затрагивает UI, ViewModel и use case-ы — меняется только привязка ниже.
 */
@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {

    /** Здесь подключается другой STT-движок: Whisper, Vosk, ML Kit, OpenAI Realtime. */
    @Binds
    @Singleton
    abstract fun bindSpeechEngine(impl: RemoteWhisperSpeechEngine): SpeechEngine

    @Binds
    @Singleton
    abstract fun bindSpeechRepository(impl: SpeechRepositoryImpl): SpeechRepository

    /**
     * Боевой клиент: адрес backend-а задаётся через `BuildConfig.API_BASE_URL`.
     * Для работы без сервера замените на `FakeNetworkRepository` — больше
     * ничего менять не нужно.
     */
    @Binds
    @Singleton
    abstract fun bindNetworkRepository(impl: RetrofitNetworkRepository): NetworkRepository
}
