package com.example.ecommerceragagent.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.ecommerceragagent.data.api.ChatApiService
import com.example.ecommerceragagent.data.api.ChatEvent
import com.example.ecommerceragagent.data.model.Message
import com.example.ecommerceragagent.data.model.MessageRole
import com.example.ecommerceragagent.data.model.Product
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

data class ChatUiState(
    val messages: List<Message> = listOf(
        Message(
            role = MessageRole.Assistant,
            content = "你好，我是电商导购助手。告诉我你的预算、品类或使用场景，我会根据商品库推荐合适的商品。"
        )
    ),
    val isLoading: Boolean = false,
    val conversationId: String = UUID.randomUUID().toString()
)

class ChatViewModel(
    private val apiService: ChatApiService = ChatApiService()
) : ViewModel() {
    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    private var activeJob: Job? = null

    fun sendMessage(text: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty() || _uiState.value.isLoading) {
            return
        }

        val assistantMessage = Message(
            role = MessageRole.Assistant,
            content = "",
            isStreaming = true
        )

        _uiState.update { state ->
            state.copy(
                messages = state.messages +
                    Message(role = MessageRole.User, content = trimmed) +
                    assistantMessage,
                isLoading = true
            )
        }

        activeJob = viewModelScope.launch {
            apiService.streamChat(trimmed, _uiState.value.conversationId).collect { event ->
                when (event) {
                    is ChatEvent.ProductFound -> appendProduct(assistantMessage.id, event.product)
                    is ChatEvent.Token -> appendToken(assistantMessage.id, event.content)
                    ChatEvent.Done -> finishStreaming(assistantMessage.id)
                    is ChatEvent.Error -> showError(assistantMessage.id, event.message)
                }
            }
        }
    }

    fun cancelResponse() {
        activeJob?.cancel()
        activeJob = null
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.isStreaming) {
                        message.copy(isStreaming = false)
                    } else {
                        message
                    }
                },
                isLoading = false
            )
        }
    }

    override fun onCleared() {
        activeJob?.cancel()
        super.onCleared()
    }

    private fun appendProduct(messageId: String, product: Product) {
        updateMessage(messageId) { message ->
            if (message.products.any { it.productId == product.productId }) {
                message
            } else {
                message.copy(products = message.products + product)
            }
        }
    }

    private fun appendToken(messageId: String, token: String) {
        updateMessage(messageId) { message ->
            message.copy(content = message.content + token)
        }
    }

    private fun finishStreaming(messageId: String) {
        activeJob = null
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.id == messageId) {
                        message.copy(isStreaming = false)
                    } else {
                        message
                    }
                },
                isLoading = false
            )
        }
    }

    private fun showError(messageId: String, error: String) {
        activeJob = null
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.id == messageId) {
                        message.copy(
                            content = "连接后端失败：$error",
                            isStreaming = false,
                            isError = true
                        )
                    } else {
                        message
                    }
                },
                isLoading = false
            )
        }
    }

    private fun updateMessage(messageId: String, transform: (Message) -> Message) {
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.id == messageId) {
                        transform(message)
                    } else {
                        message
                    }
                }
            )
        }
    }
}
