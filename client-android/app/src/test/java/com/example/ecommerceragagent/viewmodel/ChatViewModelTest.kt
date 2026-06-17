package com.example.ecommerceragagent.viewmodel

import com.example.ecommerceragagent.data.api.ChatEvent
import com.example.ecommerceragagent.data.api.ChatService
import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.Message
import com.example.ecommerceragagent.data.model.MessageBlock
import com.example.ecommerceragagent.data.model.MessageRole
import com.example.ecommerceragagent.data.model.ProductDetail
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TestWatcher
import org.junit.runner.Description

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @Test
    fun sendMessage_replaysBlockThatArrivesBeforeMessageStart() = runTest(mainDispatcherRule.dispatcher) {
        val viewModel = ChatViewModel(
            FakeChatService(
                flowOf(
                    ChatEvent.BlockTextDelta("asst-1", "attempt-1", "blk-1", "A"),
                    ChatEvent.MessageStart("asst-1", "attempt-1"),
                    ChatEvent.BlockTextDelta("asst-1", "attempt-1", "blk-1", "B"),
                    ChatEvent.MessageCommit("asst-1", "attempt-1"),
                    ChatEvent.Done
                )
            )
        )

        viewModel.sendMessage("hello")
        advanceUntilIdle()

        val assistant = viewModel.uiState.value.latestAssistantMessage()
        assertEquals("asst-1", assistant.id)
        assertEquals("AB", assistant.textContent())
        assertFalse(assistant.isStreaming)
        assertFalse(viewModel.uiState.value.isLoading)
    }

    @Test
    fun sendMessage_resetClearsCurrentAttemptAndIgnoresStaleBlocks() = runTest(mainDispatcherRule.dispatcher) {
        val viewModel = ChatViewModel(
            FakeChatService(
                flowOf(
                    ChatEvent.MessageStart("asst-1", "attempt-1"),
                    ChatEvent.BlockTextDelta("asst-1", "attempt-1", "blk-1", "bad"),
                    ChatEvent.MessageReset("asst-1", "attempt-1", "retry"),
                    ChatEvent.MessageStart("asst-1", "attempt-2"),
                    ChatEvent.BlockTextDelta("asst-1", "attempt-1", "blk-1", "stale"),
                    ChatEvent.BlockTextDelta("asst-1", "attempt-2", "blk-1", "good"),
                    ChatEvent.MessageCommit("asst-1", "attempt-2"),
                    ChatEvent.Done
                )
            )
        )

        viewModel.sendMessage("hello")
        advanceUntilIdle()

        val assistant = viewModel.uiState.value.latestAssistantMessage()
        assertEquals("good", assistant.textContent())
        assertFalse(assistant.isStreaming)
        assertFalse(viewModel.uiState.value.isLoading)
    }

    @Test
    fun sendMessage_errorReplacesCurrentProvisionalContent() = runTest(mainDispatcherRule.dispatcher) {
        val viewModel = ChatViewModel(
            FakeChatService(
                flowOf(
                    ChatEvent.MessageStart("asst-1", "attempt-1"),
                    ChatEvent.BlockTextDelta("asst-1", "attempt-1", "blk-1", "bad"),
                    ChatEvent.Error("failed")
                )
            )
        )

        viewModel.sendMessage("hello")
        advanceUntilIdle()

        val assistant = viewModel.uiState.value.latestAssistantMessage()
        assertEquals(1, assistant.blocks.size)
        assertTrue(assistant.textContent().contains("failed"))
        assertTrue(assistant.isError)
        assertFalse(assistant.isStreaming)
        assertFalse(viewModel.uiState.value.isLoading)
    }

    @Test
    fun sendMessage_acceptsLegacyBlocksWithoutMessageStart() = runTest(mainDispatcherRule.dispatcher) {
        val viewModel = ChatViewModel(
            FakeChatService(
                flowOf(
                    ChatEvent.BlockTextDelta("", "attempt-1", "blk-1", "legacy"),
                    ChatEvent.Done
                )
            )
        )

        viewModel.sendMessage("hello")
        advanceUntilIdle()

        val assistant = viewModel.uiState.value.latestAssistantMessage()
        assertEquals("legacy", assistant.textContent())
        assertFalse(assistant.isStreaming)
        assertFalse(viewModel.uiState.value.isLoading)
    }

    @Test
    fun cancelResponseStopsLoadingAndMarksStreamingMessageInterrupted() = runTest(mainDispatcherRule.dispatcher) {
        val viewModel = ChatViewModel(
            FakeChatService(
                flow {
                    awaitCancellation()
                }
            )
        )

        viewModel.sendMessage("hello")
        advanceUntilIdle()
        viewModel.cancelResponse()
        advanceUntilIdle()

        val assistant = viewModel.uiState.value.latestAssistantMessage()
        assertTrue(assistant.interrupted)
        assertFalse(assistant.isStreaming)
        assertFalse(viewModel.uiState.value.isLoading)
    }

    private fun ChatUiState.latestAssistantMessage(): Message {
        return messages.last { it.role == MessageRole.Assistant }
    }

    private fun Message.textContent(): String {
        return blocks.filterIsInstance<MessageBlock.TextBlock>()
            .joinToString(separator = "") { it.content }
    }
}

private class FakeChatService(
    private val events: Flow<ChatEvent>
) : ChatService {
    override fun streamChat(message: String, conversationId: String?): Flow<ChatEvent> = events
    override suspend fun getCart(conversationId: String): Cart = unsupported()
    override suspend fun getProductDetail(productId: String): ProductDetail = unsupported()
    override suspend fun addCartItem(
        conversationId: String,
        productId: String,
        quantity: Int
    ): Cart = unsupported()
    override suspend fun updateCartItem(
        conversationId: String,
        productId: String,
        quantity: Int
    ): Cart = unsupported()
    override suspend fun removeCartItem(conversationId: String, productId: String): Cart = unsupported()
    override suspend fun clearCart(conversationId: String): Cart = unsupported()

    private fun unsupported(): Nothing {
        throw UnsupportedOperationException("Cart and product APIs are not used in these tests.")
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class MainDispatcherRule(
    val dispatcher: TestDispatcher = StandardTestDispatcher()
) : TestWatcher() {
    override fun starting(description: Description) {
        Dispatchers.setMain(dispatcher)
    }

    override fun finished(description: Description) {
        Dispatchers.resetMain()
    }
}
