package com.example.ecommerceragagent.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.ecommerceragagent.data.api.ChatApiService
import com.example.ecommerceragagent.data.api.ChatEvent
import com.example.ecommerceragagent.data.api.ChatService
import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.Message
import com.example.ecommerceragagent.data.model.MessageBlock
import com.example.ecommerceragagent.data.model.MessageRole
import com.example.ecommerceragagent.data.model.Product
import com.example.ecommerceragagent.data.model.ProductDetail
import com.example.ecommerceragagent.data.model.StreamingStatus
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
            blocks = listOf(
                MessageBlock.TextBlock(
                    id = "welcome",
                    content = "你好，我是你的电商导购助手。告诉我预算、品类或使用场景，我会根据商品库推荐合适的商品。"
                )
            )
        )
    ),
    val isLoading: Boolean = false,
    val streamingStatus: StreamingStatus? = null,
    val conversationId: String = UUID.randomUUID().toString(),
    val cart: Cart = Cart.empty(conversationId),
    val isCartLoading: Boolean = false,
    val cartError: String? = null,
    val productDetail: ProductDetail? = null,
    val isProductDetailLoading: Boolean = false,
    val productDetailError: String? = null
)

class ChatViewModel(
    private val apiService: ChatService = ChatApiService()
) : ViewModel() {
    private val _uiState = MutableStateFlow(ChatUiState())
    val uiState: StateFlow<ChatUiState> = _uiState.asStateFlow()

    private var activeJob: Job? = null
    private var activeAssistantMessageId: String? = null
    private var activeAttemptId: String? = null
    private var activeAttemptCommitted: Boolean = false
    private val pendingBlocks = mutableMapOf<AttemptKey, MutableList<ChatEvent>>()

    fun sendMessage(text: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty() || _uiState.value.isLoading) {
            return
        }

        val assistantMessage = Message(
            role = MessageRole.Assistant,
            blocks = emptyList(),
            isStreaming = true
        )
        activeAssistantMessageId = assistantMessage.id
        activeAttemptId = null
        activeAttemptCommitted = false
        pendingBlocks.clear()

        _uiState.update { state ->
            state.copy(
                messages = state.messages +
                    Message(
                        role = MessageRole.User,
                        blocks = listOf(
                            MessageBlock.TextBlock(
                                id = UUID.randomUUID().toString(),
                                content = trimmed
                            )
                        )
                    ) +
                    assistantMessage,
                isLoading = true,
                streamingStatus = null
            )
        }

        activeJob = viewModelScope.launch {
            apiService.streamChat(trimmed, _uiState.value.conversationId).collect { event ->
                when (event) {
                    is ChatEvent.StructuredStatus -> updateStatus(event.status)
                    is ChatEvent.CartUpdated -> updateCart(event.cart)
                    is ChatEvent.MessageStart -> handleMessageStart(
                        previousMessageId = activeAssistantMessageId ?: assistantMessage.id,
                        messageId = event.messageId,
                        attemptId = event.attemptId
                    )
                    is ChatEvent.MessageReset -> handleMessageReset(
                        messageId = event.messageId,
                        attemptId = event.attemptId
                    )
                    is ChatEvent.MessageCommit -> handleMessageCommit(
                        messageId = event.messageId,
                        attemptId = event.attemptId
                    )
                    is ChatEvent.BlockText -> handleBlock(event)
                    is ChatEvent.BlockTextDelta -> handleBlock(event)
                    is ChatEvent.BlockProduct -> handleBlock(event)
                    is ChatEvent.BlockCompare -> handleBlock(event)
                    ChatEvent.Done -> finishStreaming(activeAssistantMessageId ?: assistantMessage.id)
                    is ChatEvent.Error -> showError(
                        activeAssistantMessageId ?: assistantMessage.id,
                        event.message
                    )
                }
            }
        }
    }

    fun refreshCart() {
        launchCartOperation {
            apiService.getCart(_uiState.value.conversationId)
        }
    }

    fun openProductDetail(product: Product) {
        viewModelScope.launch {
            _uiState.update {
                it.copy(
                    productDetail = null,
                    isProductDetailLoading = true,
                    productDetailError = null
                )
            }
            try {
                val detail = apiService.getProductDetail(product.productId)
                _uiState.update {
                    it.copy(
                        productDetail = detail,
                        isProductDetailLoading = false
                    )
                }
            } catch (error: Exception) {
                _uiState.update {
                    it.copy(
                        productDetail = null,
                        isProductDetailLoading = false,
                        productDetailError = error.message ?: "商品详情加载失败"
                    )
                }
            }
        }
    }

    fun dismissProductDetail() {
        _uiState.update {
            it.copy(
                productDetail = null,
                isProductDetailLoading = false,
                productDetailError = null
            )
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
        activeAssistantMessageId = null
        activeAttemptId = null
        activeAttemptCommitted = false
        pendingBlocks.clear()
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.isStreaming) {
                        message.copy(isStreaming = false, interrupted = true)
                    } else {
                        message
                    }
                },
                isLoading = false,
                streamingStatus = null
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

    private fun handleMessageStart(
        previousMessageId: String,
        messageId: String,
        attemptId: String
    ) {
        activeAssistantMessageId = messageId
        activeAttemptId = attemptId
        activeAttemptCommitted = false
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.id == previousMessageId || message.id == messageId) {
                        message.copy(
                            id = messageId,
                            blocks = emptyList(),
                            isStreaming = true,
                            isError = false,
                            interrupted = false
                        )
                    } else {
                        message
                    }
                }
            )
        }
        val pending = pendingBlocks.remove(AttemptKey(messageId, attemptId)).orEmpty()
        pending.forEach { applyBlock(it, messageId) }
    }

    private fun handleMessageReset(messageId: String, attemptId: String) {
        if (!isCurrentAttempt(messageId, attemptId)) {
            return
        }
        activeAttemptCommitted = false
        pendingBlocks.remove(AttemptKey(messageId, attemptId))
        updateMessage(messageId) { message ->
            message.copy(
                blocks = emptyList(),
                isStreaming = true,
                isError = false,
                interrupted = false
            )
        }
    }

    private fun handleMessageCommit(messageId: String, attemptId: String) {
        if (!isCurrentAttempt(messageId, attemptId)) {
            return
        }
        activeAttemptCommitted = true
        pendingBlocks.remove(AttemptKey(messageId, attemptId))
        updateMessage(messageId) { message ->
            message.copy(isStreaming = false)
        }
    }

    private fun handleBlock(event: ChatEvent) {
        val messageId = event.messageId()
        val attemptId = event.attemptId()
        val targetMessageId = currentTargetForBlock(messageId, attemptId)
        if (targetMessageId == null) {
            if (activeAttemptId == null && messageId.isNotBlank()) {
                pendingBlocks.getOrPut(AttemptKey(messageId, attemptId)) { mutableListOf() }
                    .add(event)
            }
            return
        }
        if (activeAttemptCommitted) {
            return
        }
        applyBlock(event, targetMessageId)
    }

    private fun applyBlock(event: ChatEvent, targetMessageId: String) {
        when (event) {
            is ChatEvent.BlockText -> {
                updateMessage(targetMessageId) { message ->
                    message.copy(
                        blocks = message.blocks.replaceOrAppendBlock(event.blockId) {
                            MessageBlock.TextBlock(id = event.blockId, content = event.content)
                        }
                    )
                }
            }
            is ChatEvent.BlockTextDelta -> {
                updateMessage(targetMessageId) { message ->
                    val index = message.blocks.indexOfFirst { it.id == event.blockId }
                    val blocks = if (index >= 0) {
                        message.blocks.mapIndexed { blockIndex, block ->
                            if (blockIndex == index && block is MessageBlock.TextBlock) {
                                block.copy(content = block.content + event.content)
                            } else {
                                block
                            }
                        }
                    } else {
                        message.blocks + MessageBlock.TextBlock(
                            id = event.blockId,
                            content = event.content
                        )
                    }
                    message.copy(blocks = blocks)
                }
            }
            is ChatEvent.BlockProduct -> {
                updateMessage(targetMessageId) { message ->
                    message.copy(
                        blocks = message.blocks.replaceOrAppendBlock(event.blockId) {
                            MessageBlock.ProductBlock(id = event.blockId, product = event.product)
                        }
                    )
                }
            }
            is ChatEvent.BlockCompare -> {
                updateMessage(targetMessageId) { message ->
                    message.copy(
                        blocks = message.blocks.replaceOrAppendBlock(event.blockId) {
                            MessageBlock.CompareBlock(id = event.blockId, table = event.table)
                        }
                    )
                }
            }
            else -> return
        }
        clearStreamingStatus()
    }

    private fun updateStatus(status: StreamingStatus) {
        _uiState.update { it.copy(streamingStatus = status) }
    }

    private fun clearStreamingStatus() {
        if (_uiState.value.streamingStatus != null) {
            _uiState.update { it.copy(streamingStatus = null) }
        }
    }

    private fun finishStreaming(messageId: String) {
        if (activeAttemptId == null && pendingBlocks.size == 1) {
            val key = pendingBlocks.keys.single()
            handleMessageStart(
                previousMessageId = messageId,
                messageId = key.messageId,
                attemptId = key.attemptId
            )
        }
        activeJob = null
        activeAssistantMessageId = null
        activeAttemptId = null
        activeAttemptCommitted = false
        pendingBlocks.clear()
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.id == messageId) {
                        message.copy(isStreaming = false)
                    } else {
                        message
                    }
                },
                isLoading = false,
                streamingStatus = null
            )
        }
    }

    private fun showError(messageId: String, error: String) {
        activeJob = null
        activeAssistantMessageId = null
        activeAttemptId = null
        activeAttemptCommitted = false
        pendingBlocks.clear()
        _uiState.update { state ->
            state.copy(
                messages = state.messages.map { message ->
                    if (message.id == messageId) {
                        message.copy(
                            blocks = listOf(
                                MessageBlock.TextBlock(
                                    id = "error",
                                    content = "连接后端失败：$error"
                                )
                            ),
                            isStreaming = false,
                            isError = true
                        )
                    } else {
                        message
                    }
                },
                isLoading = false,
                streamingStatus = null
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

    private fun isCurrentAttempt(messageId: String, attemptId: String): Boolean {
        return activeAssistantMessageId == messageId && activeAttemptId == attemptId
    }

    private fun currentTargetForBlock(messageId: String, attemptId: String): String? {
        val activeMessageId = activeAssistantMessageId ?: return null
        val currentAttemptId = activeAttemptId
        if (currentAttemptId == null) {
            if (messageId.isBlank()) {
                activeAttemptId = attemptId
                return activeMessageId
            }
            return null
        }
        return if (activeMessageId == messageId && currentAttemptId == attemptId) {
            activeMessageId
        } else {
            null
        }
    }

    private fun ChatEvent.messageId(): String {
        return when (this) {
            is ChatEvent.BlockText -> messageId
            is ChatEvent.BlockTextDelta -> messageId
            is ChatEvent.BlockProduct -> messageId
            is ChatEvent.BlockCompare -> messageId
            else -> ""
        }
    }

    private fun ChatEvent.attemptId(): String {
        return when (this) {
            is ChatEvent.BlockText -> attemptId
            is ChatEvent.BlockTextDelta -> attemptId
            is ChatEvent.BlockProduct -> attemptId
            is ChatEvent.BlockCompare -> attemptId
            else -> ""
        }
    }

    private fun List<MessageBlock>.replaceOrAppendBlock(
        blockId: String,
        create: () -> MessageBlock
    ): List<MessageBlock> {
        val index = indexOfFirst { it.id == blockId }
        return if (index >= 0) {
            mapIndexed { itemIndex, block -> if (itemIndex == index) create() else block }
        } else {
            this + create()
        }
    }

    private data class AttemptKey(val messageId: String, val attemptId: String)
}
