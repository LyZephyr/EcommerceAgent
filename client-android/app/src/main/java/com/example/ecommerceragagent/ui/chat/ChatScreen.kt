package com.example.ecommerceragagent.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddShoppingCart
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.example.ecommerceragagent.data.model.Cart
import com.example.ecommerceragagent.data.model.CartItem
import com.example.ecommerceragagent.data.model.CompareTable
import com.example.ecommerceragagent.data.model.Message
import com.example.ecommerceragagent.data.model.MessageBlock
import com.example.ecommerceragagent.data.model.MessageRole
import com.example.ecommerceragagent.data.model.Product
import com.example.ecommerceragagent.data.model.ProductDetail
import com.example.ecommerceragagent.data.model.StreamingStatus
import com.example.ecommerceragagent.viewmodel.ChatViewModel
import java.text.NumberFormat
import java.util.Locale

@Composable
fun ChatRoute(
    viewModel: ChatViewModel = viewModel()
) {
    val uiState by viewModel.uiState.collectAsState()
    ChatScreen(
        messages = uiState.messages,
        isLoading = uiState.isLoading,
        streamingStatus = uiState.streamingStatus,
        cart = uiState.cart,
        isCartLoading = uiState.isCartLoading,
        cartError = uiState.cartError,
        productDetail = uiState.productDetail,
        isProductDetailLoading = uiState.isProductDetailLoading,
        productDetailError = uiState.productDetailError,
        onSendMessage = viewModel::sendMessage,
        onCancelResponse = viewModel::cancelResponse,
        onAddToCart = viewModel::addToCart,
        onOpenProduct = viewModel::openProductDetail,
        onDismissProduct = viewModel::dismissProductDetail,
        onRefreshCart = viewModel::refreshCart,
        onIncrementCartItem = viewModel::incrementCartItem,
        onDecrementCartItem = viewModel::decrementCartItem,
        onRemoveCartItem = viewModel::removeCartItem,
        onClearCart = viewModel::clearCart
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    messages: List<Message>,
    isLoading: Boolean,
    streamingStatus: StreamingStatus?,
    cart: Cart,
    isCartLoading: Boolean,
    cartError: String?,
    productDetail: ProductDetail?,
    isProductDetailLoading: Boolean,
    productDetailError: String?,
    onSendMessage: (String) -> Unit,
    onCancelResponse: () -> Unit,
    onAddToCart: (Product) -> Unit,
    onOpenProduct: (Product) -> Unit,
    onDismissProduct: () -> Unit,
    onRefreshCart: () -> Unit,
    onIncrementCartItem: (String) -> Unit,
    onDecrementCartItem: (String) -> Unit,
    onRemoveCartItem: (String) -> Unit,
    onClearCart: () -> Unit
) {
    val listState = rememberLazyListState()
    var input by rememberSaveable { mutableStateOf("") }
    var showCart by rememberSaveable { mutableStateOf(false) }

    LaunchedEffect(messages, streamingStatus?.message) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    if (showCart) {
        CartSheet(
            cart = cart,
            isCartLoading = isCartLoading,
            cartError = cartError,
            onDismiss = { showCart = false },
            onIncrement = onIncrementCartItem,
            onDecrement = onDecrementCartItem,
            onRemove = onRemoveCartItem,
            onClear = onClearCart
        )
    }

    if (isProductDetailLoading || productDetail != null || productDetailError != null) {
        ProductDetailSheet(
            detail = productDetail,
            isLoading = isProductDetailLoading,
            error = productDetailError,
            onDismiss = onDismissProduct,
            onAddToCart = { productDetail?.product?.let(onAddToCart) }
        )
    }

    Scaffold(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing),
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = "电商导购助手",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.SemiBold
                        )
                        Text(
                            text = streamingStatus?.message ?: "RAG 商品推荐",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                },
                actions = {
                    IconButton(
                        onClick = {
                            onRefreshCart()
                            showCart = true
                        }
                    ) {
                        BadgedBox(
                            badge = {
                                if (cart.totalQuantity > 0) {
                                    Badge { Text(cart.totalQuantity.toString()) }
                                }
                            }
                        ) {
                            Icon(
                                imageVector = Icons.Default.ShoppingCart,
                                contentDescription = "购物车"
                            )
                        }
                    }
                }
            )
        },
        bottomBar = {
            Column {
                if (cart.totalQuantity > 0 || cartError != null || cart.messages.isNotEmpty()) {
                    CartSummaryBar(
                        cart = cart,
                        cartError = cartError,
                        isCartLoading = isCartLoading,
                        onClick = {
                            onRefreshCart()
                            showCart = true
                        }
                    )
                }
                ChatInputBar(
                    input = input,
                    isLoading = isLoading,
                    onInputChange = { input = it },
                    onSend = {
                        onSendMessage(input)
                        input = ""
                    },
                    onCancel = onCancelResponse
                )
            }
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .padding(padding),
            state = listState,
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            items(messages, key = { it.id }) { message ->
                MessageItem(
                    message = message,
                    onProductClick = onOpenProduct,
                    onAddToCart = onAddToCart
                )
            }
            if (streamingStatus != null) {
                item(key = "streaming-status") {
                    StreamingStatusCard(status = streamingStatus)
                }
            }
        }
    }
}

@Composable
private fun MessageItem(
    message: Message,
    onProductClick: (Product) -> Unit,
    onAddToCart: (Product) -> Unit
) {
    val isUser = message.role == MessageRole.User
    val alignment = if (isUser) Alignment.End else Alignment.Start
    var previousGroup: String? = null

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = alignment,
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        if (message.blocks.isEmpty() && message.isStreaming) {
            TypingBubble()
        }
        message.blocks.forEach { block ->
            when (block) {
                is MessageBlock.TextBlock -> MessageBubble(
                    text = block.content,
                    isUser = isUser,
                    isError = message.isError
                )
                is MessageBlock.ProductBlock -> {
                    val group = block.product.groupLabel
                    if (!group.isNullOrBlank() && group != previousGroup) {
                        GroupLabel(text = group)
                    }
                    previousGroup = group
                    ProductCard(
                        product = block.product,
                        onClick = { onProductClick(block.product) },
                        onAddToCart = { onAddToCart(block.product) }
                    )
                }
                is MessageBlock.CompareBlock -> CompareTableCard(table = block.table)
            }
        }
        if (message.interrupted) {
            Text(
                text = "已停止生成",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun MessageBubble(
    text: String,
    isUser: Boolean,
    isError: Boolean = false
) {
    if (text.isBlank()) {
        return
    }
    val background = when {
        isError -> MaterialTheme.colorScheme.errorContainer
        isUser -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.surfaceVariant
    }
    val contentColor = when {
        isError -> MaterialTheme.colorScheme.onErrorContainer
        isUser -> MaterialTheme.colorScheme.onPrimary
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }

    Surface(
        modifier = Modifier.widthIn(max = 340.dp),
        shape = RoundedCornerShape(
            topStart = 8.dp,
            topEnd = 8.dp,
            bottomStart = if (isUser) 8.dp else 2.dp,
            bottomEnd = if (isUser) 2.dp else 8.dp
        ),
        color = background,
        contentColor = contentColor
    ) {
        Text(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            text = text,
            style = MaterialTheme.typography.bodyLarge
        )
    }
}

@Composable
private fun TypingBubble() {
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surfaceVariant
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
            Text(
                text = "正在整理推荐...",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun StreamingStatusCard(status: StreamingStatus) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = status.message,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                if (status.step != null && status.totalSteps != null) {
                    Text(
                        text = "${status.step}/${status.totalSteps}",
                        style = MaterialTheme.typography.labelMedium
                    )
                }
            }
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun GroupLabel(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.primary,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.padding(top = 4.dp)
    )
}

@Composable
private fun CompareTableCard(table: CompareTable) {
    if (table.products.isEmpty() || table.rows.isEmpty()) {
        return
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(
                text = "商品对比",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold
            )
            if (table.products.size > 3) {
                Text(
                    text = "当前对比商品较多，建议选择 2-3 个重点商品继续追问。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            table.rows.forEach { row ->
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        text = row.dimension,
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = FontWeight.SemiBold
                    )
                    table.products.forEach { product ->
                        Text(
                            text = "${product.title}：${row.values[product.productId].orEmpty().ifBlank { "-" }}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ProductCard(
    product: Product,
    onClick: () -> Unit,
    onAddToCart: () -> Unit
) {
    val priceText = remember(product.price) { formatPrice(product.price) }
    val statusText = product.unavailableReason ?: stockStatusText(product.stockStatus, product.stock)
    val canAddToCart = product.unavailableReason == null &&
        product.stockStatus != "inactive" &&
        product.stockStatus != "out_of_stock"

    Card(
        modifier = Modifier
            .fillMaxWidth(0.92f)
            .widthIn(max = 420.dp)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            ProductImage(
                imageUrl = product.imageUrl,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1.45f)
                    .clip(RoundedCornerShape(6.dp))
            )
            Text(
                text = product.title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = priceText,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = product.brand ?: product.category,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            if (!statusText.isNullOrBlank()) {
                Text(
                    text = statusText,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (canAddToCart) {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    } else {
                        MaterialTheme.colorScheme.error
                    }
                )
            }
            if (product.highlights.isNotEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    product.highlights.take(2).forEach { highlight ->
                        AssistChip(onClick = onClick, label = { Text(highlight, maxLines = 1) })
                    }
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Button(
                    modifier = Modifier.weight(1f),
                    onClick = onClick
                ) {
                    Text("查看详情")
                }
                FilledTonalButton(
                    enabled = canAddToCart,
                    onClick = onAddToCart
                ) {
                    Icon(imageVector = Icons.Default.AddShoppingCart, contentDescription = null)
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("加入")
                }
            }
        }
    }
}

@Composable
private fun ProductImage(
    imageUrl: String?,
    modifier: Modifier = Modifier
) {
    if (imageUrl == null) {
        Box(
            modifier = modifier.background(MaterialTheme.colorScheme.secondaryContainer),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = "暂无图片",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
        }
    } else {
        AsyncImage(
            model = imageUrl,
            contentDescription = null,
            modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant),
            contentScale = ContentScale.Crop
        )
    }
}

@Composable
private fun ChatInputBar(
    input: String,
    isLoading: Boolean,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onCancel: () -> Unit
) {
    Surface(
        tonalElevation = 3.dp,
        color = MaterialTheme.colorScheme.surface
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .imePadding()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                modifier = Modifier.weight(1f),
                value = input,
                onValueChange = onInputChange,
                placeholder = { Text("输入需求，例如：推荐一款适合油皮的洗面奶") },
                minLines = 1,
                maxLines = 4,
                enabled = !isLoading
            )
            if (isLoading) {
                IconButton(
                    modifier = Modifier.size(48.dp),
                    onClick = onCancel
                ) {
                    Icon(imageVector = Icons.Default.Close, contentDescription = "停止")
                }
            } else {
                IconButton(
                    modifier = Modifier.size(48.dp),
                    enabled = input.isNotBlank(),
                    onClick = onSend
                ) {
                    Icon(imageVector = Icons.AutoMirrored.Filled.Send, contentDescription = "发送")
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProductDetailSheet(
    detail: ProductDetail?,
    isLoading: Boolean,
    error: String?,
    onDismiss: () -> Unit,
    onAddToCart: () -> Unit
) {
    val uriHandler = LocalUriHandler.current
    val product = detail?.product
    val canAddToCart = product != null &&
        product.unavailableReason == null &&
        product.stockStatus != "inactive" &&
        product.stockStatus != "out_of_stock"

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            when {
                isLoading -> {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(180.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator()
                    }
                }
                error != null -> {
                    Text(
                        text = error,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error
                    )
                }
                detail != null && product != null -> {
                    ProductImage(
                        imageUrl = product.imageUrl,
                        modifier = Modifier
                            .fillMaxWidth()
                            .aspectRatio(1.55f)
                            .clip(RoundedCornerShape(8.dp))
                    )
                    Text(
                        text = product.title,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold
                    )
                    ProductInfoRow(label = "价格", value = formatPrice(product.price))
                    product.brand?.let { ProductInfoRow(label = "品牌", value = it) }
                    ProductInfoRow(label = "品类", value = product.subCategory ?: product.category)
                    ProductInfoRow(
                        label = "库存",
                        value = stockStatusText(product.stockStatus, product.stock) ?: "有货"
                    )
                    product.unavailableReason?.let {
                        Text(
                            text = it,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error
                        )
                    }
                    detail.description?.takeIf { it.isNotBlank() }?.let {
                        SectionText(title = "商品描述", content = it)
                    }
                    if (product.highlights.isNotEmpty()) {
                        SectionText(title = "卖点", content = product.highlights.joinToString(" / "))
                    }
                    detail.specs.takeIf { it.isNotEmpty() }?.let { specs ->
                        SectionText(
                            title = "规格",
                            content = specs.joinToString("\n") { "${it.name}：${it.value}" }
                        )
                    }
                    detail.reviewSummary?.let { review ->
                        val rating = review.averageRating?.let { "评分 $it" }
                        val count = review.totalCount?.let { "${it} 条评价" }
                        SectionText(
                            title = "评价",
                            content = listOfNotNull(rating, count)
                                .plus(review.highlights)
                                .joinToString(" / ")
                        )
                    }
                    detail.faq.takeIf { it.isNotEmpty() }?.let { faq ->
                        SectionText(
                            title = "FAQ",
                            content = faq.joinToString("\n") { "Q：${it.question}\nA：${it.answer}" }
                        )
                    }
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            modifier = Modifier.weight(1f),
                            enabled = canAddToCart,
                            onClick = onAddToCart
                        ) {
                            Icon(imageVector = Icons.Default.AddShoppingCart, contentDescription = null)
                            Spacer(modifier = Modifier.width(6.dp))
                            Text("加入购物车")
                        }
                        product.landingUrl?.let { url ->
                            OutlinedButton(onClick = { uriHandler.openUri(url) }) {
                                Icon(imageVector = Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null)
                                Spacer(modifier = Modifier.width(6.dp))
                                Text("商品页")
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SectionText(title: String, content: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold
        )
        Text(
            text = content,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun CartSummaryBar(
    cart: Cart,
    cartError: String?,
    isCartLoading: Boolean,
    onClick: () -> Unit
) {
    val totalText = remember(cart.totalPrice) { formatPrice(cart.totalPrice) }
    val summaryText = cartError
        ?: cart.messages.firstOrNull()
        ?: "购物车 ${cart.totalQuantity} 件"
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = !isCartLoading, onClick = onClick),
        tonalElevation = 2.dp,
        color = MaterialTheme.colorScheme.primaryContainer,
        contentColor = MaterialTheme.colorScheme.onPrimaryContainer
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                modifier = Modifier.weight(1f),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(imageVector = Icons.Default.ShoppingCart, contentDescription = null)
                Text(
                    text = summaryText,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Text(
                text = if (isCartLoading) "更新中" else totalText,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CartSheet(
    cart: Cart,
    isCartLoading: Boolean,
    cartError: String?,
    onDismiss: () -> Unit,
    onIncrement: (String) -> Unit,
    onDecrement: (String) -> Unit,
    onRemove: (String) -> Unit,
    onClear: () -> Unit
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "购物车",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold
                    )
                    Text(
                        text = "${cart.totalQuantity} 件商品 · ${formatPrice(cart.totalPrice)}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                TextButton(
                    enabled = cart.items.isNotEmpty() && !isCartLoading,
                    onClick = onClear
                ) {
                    Text("清空")
                }
            }

            if (isCartLoading) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }

            cartError?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }

            CartNoticeList(messages = cart.messages)

            if (cart.items.isEmpty()) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(160.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "购物车还是空的",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    cart.items.forEach { item ->
                        CartItemRow(
                            item = item,
                            enabled = !isCartLoading,
                            onIncrement = { onIncrement(item.productId) },
                            onDecrement = { onDecrement(item.productId) },
                            onRemove = { onRemove(item.productId) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CartNoticeList(messages: List<String>) {
    if (messages.isEmpty()) {
        return
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.secondaryContainer)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        messages.forEach { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
        }
    }
}

@Composable
private fun CartItemRow(
    item: CartItem,
    enabled: Boolean,
    onIncrement: () -> Unit,
    onDecrement: () -> Unit,
    onRemove: () -> Unit
) {
    val statusText = item.unavailableReason
        ?: when {
            item.isActive == false -> "商品已下架"
            item.stock == 0 -> "库存不足"
            item.stock != null && item.quantity > item.stock -> "库存不足，仅剩 ${item.stock} 件"
            else -> null
        }
    val canAdjustQuantity = enabled && statusText == null

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier.padding(10.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            ProductImage(
                imageUrl = item.imageUrl,
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(6.dp))
            )
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text(
                    text = item.title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = "${formatPrice(item.price)} · 小计 ${formatPrice(item.subtotal)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                statusText?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        fontWeight = FontWeight.Medium
                    )
                }
                item.stock?.let { stock ->
                    if (statusText == null) {
                        Text(
                            text = "库存 $stock 件",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(
                        modifier = Modifier.size(32.dp),
                        enabled = canAdjustQuantity,
                        onClick = onDecrement
                    ) {
                        Icon(imageVector = Icons.Default.Remove, contentDescription = "减少")
                    }
                    Text(
                        text = item.quantity.toString(),
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold
                    )
                    IconButton(
                        modifier = Modifier.size(32.dp),
                        enabled = canAdjustQuantity,
                        onClick = onIncrement
                    ) {
                        Icon(imageVector = Icons.Default.Add, contentDescription = "增加")
                    }
                }
            }
            IconButton(
                enabled = enabled,
                onClick = onRemove
            ) {
                Icon(
                    imageVector = Icons.Default.Delete,
                    contentDescription = "删除",
                    tint = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

@Composable
private fun ProductInfoRow(
    label: String,
    value: String
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurface
        )
    }
}

private fun stockStatusText(stockStatus: String?, stock: Int?): String? {
    return when (stockStatus) {
        "inactive" -> "商品已下架"
        "out_of_stock" -> "暂无库存"
        "low_stock" -> stock?.let { "库存紧张，仅剩 $it 件" } ?: "库存紧张"
        "in_stock" -> stock?.let { "库存 $it 件" }
        else -> stock?.let { "库存 $it 件" }
    }
}

private fun formatPrice(price: Double): String {
    return NumberFormat.getCurrencyInstance(Locale.CHINA).format(price)
}
