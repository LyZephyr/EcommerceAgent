package com.example.ecommerceragagent.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.ecommerceragagent.data.api.ChatApiService
import com.example.ecommerceragagent.data.api.ChatEvent
import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.CompareTable
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
            content = "你好，我是你的电商导购助手。告诉我预算、品类或使用场景，我会根据商品库推荐合适的商品。"
        )
    ),
    val isLoading: Boolean = false,
    val conversationId: String = UUID.randomUUID().toString(),
    val cart: Cart = Cart.empty(conversationId),
    val isCartLoading: Boolean = false,
    val cartError: String? = null
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
                    is ChatEvent.Status -> updateStatus(assistantMessage.id, event.message)
                    is ChatEvent.CartUpdated -> updateCart(event.cart)
                    is ChatEvent.ProductFound -> appendProduct(assistantMessage.id, event.product)
                    is ChatEvent.Compare -> appendCompareTable(assistantMessage.id, event.table)
                    is ChatEvent.Token -> appendToken(assistantMessage.id, event.content)
                    ChatEvent.Done -> finishStreaming(assistantMessage.id)
                    is ChatEvent.Error -> showError(assistantMessage.id, event.message)
                }
            }
        }
    }

    fun refreshCart() {
        launchCartOperation {
            apiService.getCart(_uiState.value.conversationId)
        }
    }

    fun addToCart(product: Product) {
        launchCartOperation {
            apiService.addCartItem(
                conversationId = _uiState.value.conversationId,
                productId = product.productId
            )
        }
    }

    fun incrementCartItem(productId: String) {
        val item = _uiState.value.cart.items.firstOrNull { it.productId == productId } ?: return
        updateCartItem(productId, item.quantity + 1)
    }

    fun decrementCartItem(productId: String) {
        val item = _uiState.value.cart.items.firstOrNull { it.productId == productId } ?: return
        if (item.quantity <= 1) {
            removeCartItem(productId)
        } else {
            updateCartItem(productId, item.quantity - 1)
        }
    }

    fun updateCartItem(productId: String, quantity: Int) {
        launchCartOperation {
            apiService.updateCartItem(
                conversationId = _uiState.value.conversationId,
                productId = productId,
                quantity = quantity
            )
        }
    }

    fun removeCartItem(productId: String) {
        launchCartOperation {
            apiService.removeCartItem(
                conversationId = _uiState.value.conversationId,
                productId = productId
            )
        }
    }

    fun clearCart() {
        launchCartOperation {
            apiService.clearCart(_uiState.value.conversationId)
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

    private fun launchCartOperation(operation: suspend () -> Cart) {
        viewModelScope.launch {
            _uiState.update { it.copy(isCartLoading = true, cartError = null) }
            try {
                val cart = operation()
                updateCart(cart)
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(cartError = error.message ?: "购物车操作失败")
                }
            } finally {
                _uiState.update { it.copy(isCartLoading = false) }
            }
        }
    }

    private fun updateCart(cart: Cart) {
        _uiState.update { state ->
            state.copy(cart = cart, cartError = null)
        }
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

    private fun appendCompareTable(messageId: String, table: CompareTable) {
        updateMessage(messageId) { message ->
            message.copy(compareTables = message.compareTables + table)
        }
    }

    private fun appendToken(messageId: String, token: String) {
        updateMessage(messageId) { message ->
            message.copy(content = message.content + token, status = null)
        }
    }

    private fun updateStatus(messageId: String, status: String) {
        updateMessage(messageId) { message ->
            message.copy(status = status)
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
