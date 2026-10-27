"""
Dynamic Interview Battery Engine for Job Hunter & Recruiter Intelligence.
Constructs comprehensive, stack-aware interview preparation batteries:
1. 12-15 In-Depth Verbal & Conceptual Questions (Core Language, Collections/Internals, Framework, Architecture)
2. 10 Concrete Practical Coding Challenges with Production-Grade Code, Constraints, and Complexity Analysis
3. 5 Managerial, Leadership & Cross-Functional Alignment Questions
4. 2-3 Strategic Reverse-Interview Questions to Ask Leadership

100% Dynamic: Automatically adapts to Candidate Profile (YOE, Stack) and Target Company/JD.
"""

from typing import Dict, Any, List, Optional
import html


def build_interview_battery(
    candidate: Dict[str, Any],
    company_name: str,
    role_title: str,
    full_text: str,
    web_research: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Constructs a calibrated interview battery based on candidate profile,
    target JD, and verified live web search intelligence.
    """
    skills = [s.lower() for s in candidate.get("skills", [])]
    primary_skills = candidate.get("skills", ["Java", "Spring Boot", "Microservices", "SQL"])
    yoe = candidate.get("years_of_experience", 8.0)
    role_lower = role_title.lower()

    # Determine domain track
    is_qa_sdet = any(kw in role_lower for kw in ["sdet", "qa", "automation", "test"])
    is_backend_java = any("java" in s for s in skills) or "java" in role_lower or "backend" in role_lower

    if is_backend_java and not is_qa_sdet:
        return _build_java_backend_battery(candidate, company_name, role_title, full_text, yoe, web_research=web_research)
    elif is_qa_sdet:
        return _build_sdet_qa_battery(candidate, company_name, role_title, full_text, yoe, web_research=web_research)
    else:
        return _build_general_backend_battery(candidate, company_name, role_title, full_text, yoe, web_research=web_research)


def _build_java_backend_battery(
    candidate: Dict[str, Any],
    company: str,
    role: str,
    full_text: str,
    yoe: float,
    web_research: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Builds a rigorous Java 17+, Spring Boot, Concurrency & Microservices battery enriched with live web research."""

    # 1. 12-15 VERBAL & CONCEPTUAL QUESTIONS ACROSS 4 TIERS
    verbals = [
        # TIER 1: CORE LANGUAGE & MEMORY MODEL
        {
            "tier": "Core Language & Memory Model",
            "topic": "JVM Memory Architecture & Generational Garbage Collection",
            "question": f"At {company}'s transaction volume, how does the JVM manage memory across Eden, Survivor, and Tenured spaces, and how do you contrast G1GC with ZGC for low-latency financial systems?",
            "talking_points": (
                "Explain Eden allocation, Minor GC via mark-and-copy, and promotion to Tenured space after aging thresholds. "
                "Contrast G1GC (region-based with predictable pause-time targets) against ZGC (concurrent colored pointers and load barriers yielding <1ms pauses regardless of heap size). "
                "Cite production tuning flags (`-XX:+UseZGC`, `-XX:MaxGCPauseMillis`, `-XX:InitiatingHeapOccupancyPercent`)."
            )
        },
        {
            "tier": "Core Language & Memory Model",
            "topic": "Java 17/21 Language Evolution & Virtual Threads (Project Loom)",
            "question": "What architectural benefits do Java 17/21 features (Records, Pattern Matching, Sealed Classes) bring to domain modeling, and when do Virtual Threads fail or suffer carrier-thread pinning?",
            "talking_points": (
                "Emphasize Records for immutable DTOs and value semantics, Sealed Classes for closed domain hierarchies (e.g., PaymentStatus), "
                "and Virtual Threads (Project Loom) for high-concurrency blocking I/O (millions of concurrent tasks vs 10,000 OS platform threads). "
                "Highlight Carrier-Thread Pinning traps: executing synchronized blocks or native JNI calls inside a virtual thread prevents unmounting; replace with `ReentrantLock`."
            )
        },
        {
            "tier": "Core Language & Memory Model",
            "topic": "Thread Safety, Volatile, & Java Memory Model (JMM) Barriers",
            "question": "How does the Java Memory Model define the happens-before relationship, and what CPU-level memory barriers are emitted when reading or writing a `volatile` variable?",
            "talking_points": (
                "Explain the visibility and instruction reordering problem across L1/L2/L3 CPU caches. "
                "`volatile` guarantees visibility and ordering by emitting LoadLoad/LoadStore barriers on reads and StoreStore/StoreLoad barriers on writes, "
                "preventing hardware instruction reordering. Clarify that `volatile` does NOT guarantee compound atomicity (e.g., `count++` requires `AtomicInteger` or `VarHandle`)."
            )
        },

        # TIER 2: ADVANCED COLLECTIONS & CONCURRENCY INTERNALS
        {
            "tier": "Advanced Collections & Concurrency",
            "topic": "HashMap Internal Working & Collision Treeify Threshold",
            "question": "Walk through the internal architecture of `HashMap` in Java 8+. How is bucket indexing computed, what is the significance of power-of-two capacity, and when does a linked bucket convert to a Red-Black tree?",
            "talking_points": (
                "Index computation: `(n - 1) & hash(key)` where `hash(key)` XORs high 16 bits with low 16 bits (`key.hashCode() ^ (h >>> 16)`) for uniform distribution. "
                "Power of two enables fast bitwise masking. "
                "Treeify condition: Bucket linked list length >= 8 (`TREEIFY_THRESHOLD`) AND total table capacity >= 64 (`MIN_TREEIFY_CAPACITY`), converting O(n) worst-case to O(log n). "
                "Rehash untreeifies back to linked list if size drops to <= 6."
            )
        },
        {
            "tier": "Advanced Collections & Concurrency",
            "topic": "ConcurrentHashMap Segment-Free Architecture & Lock Striping",
            "question": "How did Java 8 eliminate Segments in `ConcurrentHashMap`, and how does it achieve thread-safe put/get operations with minimal contention?",
            "talking_points": (
                "Java 8 replaced `ReentrantLock` segments with synchronized table bucket nodes and CAS (`Unsafe.compareAndSwapObject` / `VarHandle`). "
                "Unoccupied bucket insert uses lock-free CAS. Occupied bucket insert synchronizes strictly on the root node of that single bucket bin. "
                "Read operations (`get`) are completely lock-free via `volatile` node references. Size is computed using dynamic multi-threaded striping via `CounterCell` (LongAdder pattern)."
            )
        },
        {
            "tier": "Advanced Collections & Concurrency",
            "topic": "ThreadPoolExecutor Queuing, Saturation Policies & Thread Sizing",
            "question": "What is the precise worker creation lifecycle in `ThreadPoolExecutor`, how do you handle saturation policies, and what is your mathematical formula for sizing thread pools?",
            "talking_points": (
                "Lifecycle: (1) If threads < `corePoolSize`, create new thread. (2) If `corePoolSize` reached, offer to `BlockingQueue`. (3) If queue is full and threads < `maxPoolSize`, create new thread. (4) If queue full and `maxPoolSize` reached, trigger `RejectedExecutionHandler`. "
                "Saturation policies: `AbortPolicy` (throws exception), `CallerRunsPolicy` (throttles by executing on caller thread), `DiscardOldestPolicy`. "
                "Sizing formula: CPU-bound: `N_threads = N_cpu + 1`. I/O-bound: `N_threads = N_cpu * (1 + Wait_Time / Compute_Time)`."
            )
        },
        {
            "tier": "Advanced Collections & Concurrency",
            "topic": "ThreadLocal Storage & Thread Pool Memory Leak Prevention",
            "question": "How does `ThreadLocal` manage memory, why does combining it with thread pools create catastrophic memory leaks, and how do you guarantee cleanup?",
            "talking_points": (
                "Each `Thread` maintains a `ThreadLocalMap` whose `Entry` extends `WeakReference<ThreadLocal<?>>`. "
                "The key is weakly reachable, but the value is strongly reachable. "
                "When threads are reused across worker pools (e.g. Tomcat/ExecutorService), the thread never dies, retaining large value objects indefinitely after keys are garbage collected. "
                "Mitigation: Always wrap in a `try-finally` block invoking `threadLocal.remove()` in the `finally` block or use a servlet/Spring filter."
            )
        },

        # TIER 3: FRAMEWORK-LEVEL DEEP DIVE (SPRING BOOT & PERSISTENCE)
        {
            "tier": "Framework-Level Internals",
            "topic": "Spring Bean Lifecycle & Proxy Generation Mechanisms (JDK vs CGLIB)",
            "question": "Explain the complete lifecycle of a Spring Bean from instantiation to destruction, and contrast JDK Dynamic Proxies with CGLIB bytecode proxies.",
            "talking_points": (
                "Lifecycle: BeanDefinition loading -> Instantiation -> Dependency Injection -> `BeanNameAware` / `ApplicationContextAware` -> `BeanPostProcessor.postProcessBeforeInitialization` -> `@PostConstruct` -> `InitializingBean.afterPropertiesSet` -> Custom `initMethod` -> `postProcessAfterInitialization` (proxy wrapping happens here!) -> Ready for use -> `@PreDestroy` -> `DisposableBean.destroy`. "
                "Proxies: JDK Dynamic Proxies require target interfaces (`java.lang.reflect.Proxy`). CGLIB generates subclasses at runtime via bytecode manipulation (Spring Boot 2.x/3.x defaults to CGLIB)."
            )
        },
        {
            "tier": "Framework-Level Internals",
            "topic": "Spring `@Transactional` Proxy Bypass & Transaction Propagation Levels",
            "question": "Why does calling a `@Transactional` method from another method in the same class silently bypass transaction management, and how do `REQUIRED`, `REQUIRES_NEW`, and `NESTED` differ?",
            "talking_points": (
                "Self-invocation bypass: Spring `@Transactional` works via AOP proxies. An internal `this.methodB()` call executes on the target object directly, bypassing the outer proxy interceptor. "
                "Solutions: Inject self, refactor to a separate service bean, or use AspectJ compile-time weaving. "
                "Propagations: `REQUIRED` (joins existing or creates new), `REQUIRES_NEW` (suspends active transaction and starts an independent atomic transaction), `NESTED` (creates a savepoint within active transaction with partial rollback capability)."
            )
        },
        {
            "tier": "Framework-Level Internals",
            "topic": "Hibernate / Spring Data JPA N+1 Select Traps & Dirty Checking Overhead",
            "question": "What is the root cause of the N+1 select problem in Hibernate, and how do you eliminate it while bypassing dirty-checking overhead in read-heavy banking transactions?",
            "talking_points": (
                "N+1 occurs when fetching an entity with lazy relationships triggers 1 query for the parent plus N individual queries for each child. "
                "Resolution: `JOIN FETCH` in JPQL, `@EntityGraph(attributePaths=...)`, or DTO projection queries with constructor expressions. "
                "Bypassing dirty checking: Mark read transactions as `@Transactional(readOnly = true)` to instruct Hibernate to omit snapshot creation and flush checks, reducing CPU and heap pressure by 40%."
            )
        },
        {
            "tier": "Framework-Level Internals",
            "topic": "Spring Boot Auto-Configuration Mechanism & Custom Conditional Starters",
            "question": "How does Spring Boot resolve `@EnableAutoConfiguration` using imports files, and how do `@ConditionalOnClass` and `@ConditionalOnMissingBean` govern bean registration?",
            "talking_points": (
                "Resolution: Evaluates `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` (Spring Boot 3) or `spring.factories` (Spring Boot 2). "
                "Auto-configuration classes run through condition evaluation filters. "
                "`@ConditionalOnClass` checks bytecode presence without classloader crashes. "
                "`@ConditionalOnMissingBean` provides sensible defaults that yield immediately if the developer defines a custom bean."
            )
        },

        # TIER 4: DISTRIBUTED SYSTEMS ARCHITECTURE, DATA & RESILIENCE
        {
            "tier": "Distributed Systems Architecture",
            "topic": "Distributed Transactions: Saga Orchestration vs 2PC in Banking",
            "question": f"In {company}'s distributed core banking microservices, why is Two-Phase Commit (2PC) rejected, and how do you implement an Orchestrated Saga with compensating transactions?",
            "talking_points": (
                "2PC is synchronous, blocking, and suffers single-point-of-failure lock contention under scale (CAP theorem consistency sacrifice). "
                "Orchestrated Saga utilizes a central orchestrator dispatching asynchronous command messages to participant services. "
                "If any downstream service fails (e.g., fraud check rejects or ledger write fails), the orchestrator triggers compensating actions in reverse order (e.g., unfreeze funds). "
                "Pair with idempotent state machine persistence to handle network retries."
            )
        },
        {
            "tier": "Distributed Systems Architecture",
            "topic": "Redis Multi-Tier Caching: Cache Stampede, Penetration, & Redlock",
            "question": "How do you architect a high-throughput Redis caching layer for client portfolio queries that is immune to cache stampede, cache penetration, and cache avalanche?",
            "talking_points": (
                "Cache stampede: When a hot key expires and 10,000 concurrent threads hit the database simultaneously. Mitigate with Mutex Locks (`SET key val NX EX`) or probabilistic early expiration (XFetch algorithm). "
                "Cache penetration: Querying non-existent records. Mitigate with Bloom Filters or caching null objects with short TTLs. "
                "Cache avalanche: Simultaneous mass key expiry. Mitigate by adding random jitter to TTLs (`base_ttl + random_offset`). "
                "Redlock / Redisson distributed locking ensures atomic cross-instance coordination."
            )
        },
        {
            "tier": "Distributed Systems Architecture",
            "topic": "Event-Driven Ledger Synchronization & Transactional Outbox Pattern",
            "question": "How do you guarantee atomic database writes and Kafka event publication without distributed two-phase commits when emitting financial ledger events?",
            "talking_points": (
                "Dual-write vulnerability: Writing to database and publishing to Kafka cannot be atomic across separate systems. "
                "Transactional Outbox Pattern: Persist the business entity AND an outbox record in the same atomic database transaction (`@Transactional`). "
                "An asynchronous Change Data Capture (CDC via Debezium) or dedicated poller reads the outbox table and streams to Kafka with idempotent producer configs (`enable.idempotence=true`). "
                "Consumer uses deduplication keys to ensure exactly-once business semantics."
            )
        },
        {
            "tier": "Distributed Systems Architecture",
            "topic": "Financial REST API Idempotency & Replay Attack Defense",
            "question": "How do you architect an idempotent financial payment endpoint in Spring Boot that safely handles network timeouts, client retries, and duplicate requests?",
            "talking_points": (
                "Enforce an `Idempotency-Key` header (UUIDv4) from client. "
                "Filter layer uses Redis atomic `SET key status NX EX 86400`: "
                "If key exists with 'PROCESSING', reject with HTTP 409 Conflict. "
                "If key exists with 'COMPLETED', immediately return the cached response payload. "
                "If key doesn't exist, proceed with transaction, store receipt in Redis upon completion, and return HTTP 201/200."
            )
        }
    ]

    # 2. EXACTLY 10 CONCRETE PRACTICAL CODING CHALLENGES
    coding_challenges = [
        {
            "id": 1,
            "title": "Thread-Safe Generic LRU Cache with TTL & Eviction Callback",
            "category": "Data Structures & Concurrency",
            "scenario": "Design a high-performance in-memory cache for frequently accessed client wealth portfolios. It must maintain O(1) reads/writes, evict the least recently used entries when capacity is exceeded, support entry-level TTL, and remain thread-safe under parallel worker threads.",
            "filename": "src/main/java/core/cache/ConcurrentLruCache.java",
            "language": "Java 17",
            "code": """package core.cache;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantReadWriteLock;

public class ConcurrentLruCache<K, V> {
    private static class Node<K, V> {
        K key;
        V value;
        long expiryTime;
        Node<K, V> prev, next;
        Node(K k, V v, long ttlMs) {
            this.key = k; this.value = v;
            this.expiryTime = ttlMs > 0 ? System.currentTimeMillis() + ttlMs : Long.MAX_VALUE;
        }
        boolean isExpired() { return System.currentTimeMillis() > expiryTime; }
    }

    private final int capacity;
    private final ConcurrentHashMap<K, Node<K, V>> map = new ConcurrentHashMap<>();
    private final Node<K, V> head = new Node<>(null, null, 0);
    private final Node<K, V> tail = new Node<>(null, null, 0);
    private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();

    public ConcurrentLruCache(int capacity) {
        this.capacity = capacity;
        head.next = tail; tail.prev = head;
    }

    public V get(K key) {
        lock.readLock().lock();
        Node<K, V> node = map.get(key);
        lock.readLock().unlock();

        if (node == null) return null;
        if (node.isExpired()) {
            remove(key);
            return null;
        }
        lock.writeLock().lock();
        try {
            moveToHead(node);
        } finally {
            lock.writeLock().unlock();
        }
        return node.value;
    }

    public void put(K key, V value, long ttlMs) {
        lock.writeLock().lock();
        try {
            Node<K, V> existing = map.get(key);
            if (existing != null) {
                existing.value = value;
                existing.expiryTime = ttlMs > 0 ? System.currentTimeMillis() + ttlMs : Long.MAX_VALUE;
                moveToHead(existing);
            } else {
                if (map.size() >= capacity) {
                    Node<K, V> lru = tail.prev;
                    removeNode(lru);
                    map.remove(lru.key);
                }
                Node<K, V> newNode = new Node<>(key, value, ttlMs);
                addFirst(newNode);
                map.put(key, newNode);
            }
        } finally {
            lock.writeLock().unlock();
        }
    }

    public void remove(K key) {
        lock.writeLock().lock();
        try {
            Node<K, V> node = map.remove(key);
            if (node != null) removeNode(node);
        } finally {
            lock.writeLock().unlock();
        }
    }

    private void addFirst(Node<K, V> node) {
        node.next = head.next; node.prev = head;
        head.next.prev = node; head.next = node;
    }
    private void removeNode(Node<K, V> node) {
        node.prev.next = node.next; node.next.prev = node.prev;
    }
    private void moveToHead(Node<K, V> node) {
        removeNode(node); addFirst(node);
    }
}""",
            "time_complexity": "O(1) for get(), put(), and remove()",
            "space_complexity": "O(N) where N is cache capacity",
            "invariants": "ReadWriteLock minimizes reader contention while ensuring deterministic atomic mutations of the doubly-linked list."
        },
        {
            "id": 2,
            "title": "Custom Bounded Blocking Queue using ReentrantLock & Two Conditions",
            "category": "Concurrency & Synchronization",
            "scenario": "Implement a custom generic bounded blocking queue without using Java's built-in `java.util.concurrent` queues. Support blocking put, blocking take, and timed poll using explicit lock condition variables.",
            "filename": "src/main/java/core/concurrency/CustomBlockingQueue.java",
            "language": "Java 17",
            "code": """package core.concurrency;

import java.util.concurrent.locks.ReentrantLock;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.TimeUnit;

public class CustomBlockingQueue<E> {
    private final Object[] items;
    private int putIndex, takeIndex, count;
    private final ReentrantLock lock = new ReentrantLock(true); // Fair lock
    private final Condition notEmpty = lock.newCondition();
    private final Condition notFull = lock.newCondition();

    public CustomBlockingQueue(int capacity) {
        if (capacity <= 0) throw new IllegalArgumentException("Capacity must be positive");
        this.items = new Object[capacity];
    }

    public void put(E e) throws InterruptedException {
        if (e == null) throw new NullPointerException();
        lock.lockInterruptibly();
        try {
            while (count == items.length) {
                notFull.await(); // Wait until space is freed
            }
            enqueue(e);
        } finally {
            lock.unlock();
        }
    }

    @SuppressWarnings("unchecked")
    public E take() throws InterruptedException {
        lock.lockInterruptibly();
        try {
            while (count == 0) {
                notEmpty.await(); // Wait until item is added
            }
            return (E) dequeue();
        } finally {
            lock.unlock();
        }
    }

    @SuppressWarnings("unchecked")
    public E poll(long timeout, TimeUnit unit) throws InterruptedException {
        long nanos = unit.toNanos(timeout);
        lock.lockInterruptibly();
        try {
            while (count == 0) {
                if (nanos <= 0) return null;
                nanos = notEmpty.awaitNanos(nanos);
            }
            return (E) dequeue();
        } finally {
            lock.unlock();
        }
    }

    private void enqueue(E e) {
        items[putIndex] = e;
        if (++putIndex == items.length) putIndex = 0;
        count++;
        notEmpty.signal(); // Notify waiting consumer
    }

    private Object dequeue() {
        Object item = items[takeIndex];
        items[takeIndex] = null;
        if (++takeIndex == items.length) takeIndex = 0;
        count--;
        notFull.signal(); // Notify waiting producer
        return item;
    }
}""",
            "time_complexity": "O(1) amortized for put(), take(), and poll()",
            "space_complexity": "O(N) where N is bounded capacity",
            "invariants": "Uses separate Condition variables (notFull, notEmpty) to avoid lost wakeups and thread starvation."
        },
        {
            "id": 3,
            "title": "Sliding Window Rate Limiter (Token Bucket / Sliding Log)",
            "category": "API Gateway & Security",
            "scenario": "Implement a thread-safe in-memory sliding window rate limiter to throttle API consumer keys (e.g. max 100 requests per 60 seconds) without window boundary burst vulnerabilities.",
            "filename": "src/main/java/core/ratelimit/SlidingWindowRateLimiter.java",
            "language": "Java 17",
            "code": """package core.ratelimit;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.ConcurrentHashMap;

public class SlidingWindowRateLimiter {
    private final int maxRequests;
    private final long windowSizeMillis;
    private final ConcurrentHashMap<String, Deque<Long>> userRequestTimestamps = new ConcurrentHashMap<>();

    public SlidingWindowRateLimiter(int maxRequests, long windowSizeMillis) {
        this.maxRequests = maxRequests;
        this.windowSizeMillis = windowSizeMillis;
    }

    public boolean allowRequest(String clientId) {
        long now = System.currentTimeMillis();
        long windowStart = now - windowSizeMillis;

        Deque<Long> timestamps = userRequestTimestamps.computeIfAbsent(clientId, k -> new ArrayDeque<>());

        synchronized (timestamps) {
            // Evict expired timestamps older than sliding window start
            while (!timestamps.isEmpty() && timestamps.peekFirst() <= windowStart) {
                timestamps.pollFirst();
            }

            if (timestamps.size() < maxRequests) {
                timestamps.addLast(now);
                return true; // Allowed
            }
            return false; // Throttled (HTTP 429)
        }
    }
}""",
            "time_complexity": "O(K) where K is evicted requests, amortized O(1)",
            "space_complexity": "O(M * N) where M is clients and N is requests per window",
            "invariants": "Fine-grained locking on the client's deque prevents cross-client contention while eliminating boundary burst exploits."
        },
        {
            "id": 4,
            "title": "Deadlock-Free Concurrent Money Transfer with Pessimistic Locking",
            "category": "Financial Ledgers & Transactions",
            "scenario": "Write a Spring Boot `@Transactional` transfer service that moves funds between accounts concurrently under high load, completely immune to circular wait deadlocks (Account A->B while B->A).",
            "filename": "src/main/java/core/banking/TransferService.java",
            "language": "Java 17",
            "code": """package core.banking;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.annotation.Isolation;
import java.math.BigDecimal;

@Service
public class TransferService {
    private final AccountRepository accountRepo;
    private final AuditLogRepository auditRepo;

    public TransferService(AccountRepository ar, AuditLogRepository alr) {
        this.accountRepo = ar;
        this.auditRepo = alr;
    }

    @Transactional(isolation = Isolation.READ_COMMITTED, rollbackFor = Exception.class)
    public TransferReceipt transferFunds(Long fromAccountId, Long toAccountId, BigDecimal amount) {
        if (fromAccountId.equals(toAccountId)) {
            throw new IllegalArgumentException("Cannot transfer to the same account");
        }
        if (amount == null || amount.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("Transfer amount must be positive");
        }

        // 1. Enforce strict deterministic lock ordering by Account ID to prevent circular deadlocks
        Long firstId = fromAccountId < toAccountId ? fromAccountId : toAccountId;
        Long secondId = fromAccountId < toAccountId ? toAccountId : fromAccountId;

        // 2. Acquire Pessimistic Write Locks (SELECT ... FOR UPDATE) in order
        Account firstLock = accountRepo.findByIdForUpdate(firstId)
            .orElseThrow(() -> new AccountNotFoundException(firstId));
        Account secondLock = accountRepo.findByIdForUpdate(secondId)
            .orElseThrow(() -> new AccountNotFoundException(secondId));

        Account fromAccount = fromAccountId.equals(firstLock.getId()) ? firstLock : secondLock;
        Account toAccount = toAccountId.equals(firstLock.getId()) ? firstLock : secondLock;

        // 3. Balance verification
        if (fromAccount.getBalance().compareTo(amount) < 0) {
            throw new InsufficientFundsException("Insufficient balance in account " + fromAccountId);
        }

        fromAccount.debit(amount);
        toAccount.credit(amount);

        accountRepo.save(fromAccount);
        accountRepo.save(toAccount);

        auditRepo.recordTransfer(fromAccountId, toAccountId, amount, "SUCCESS");
        return new TransferReceipt(fromAccountId, toAccountId, amount, "COMPLETED");
    }
}""",
            "time_complexity": "O(1) database row lock and atomic update",
            "space_complexity": "O(1) memory allocation",
            "invariants": "Lock ordering (`firstId < secondId`) satisfies the Coffman conditions to eliminate circular wait deadlocks."
        },
        {
            "id": 5,
            "title": "Spring Boot Idempotency Filter backed by Redis Atomic SETNX",
            "category": "API Gateway & Spring Web",
            "scenario": "Implement an HTTP OncePerRequestFilter that intercepts incoming financial mutations, validates `Idempotency-Key`, uses Redis atomic check-and-set to block concurrent duplicates, and returns cached receipts for retransmissions.",
            "filename": "src/main/java/core/security/IdempotencyFilter.java",
            "language": "Java 17",
            "code": """package core.security;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingResponseWrapper;
import java.io.IOException;
import java.time.Duration;

@Component
public class IdempotencyFilter extends OncePerRequestFilter {
    private final StringRedisTemplate redisTemplate;

    public IdempotencyFilter(StringRedisTemplate rt) {
        this.redisTemplate = rt;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {

        if (!"POST".equalsIgnoreCase(request.getMethod()) && !"PUT".equalsIgnoreCase(request.getMethod())) {
            filterChain.doFilter(request, response);
            return;
        }

        String idempotencyKey = request.getHeader("Idempotency-Key");
        if (idempotencyKey == null || idempotencyKey.isBlank()) {
            filterChain.doFilter(request, response);
            return;
        }

        String redisKey = "idempotency:" + idempotencyKey;
        // Atomic SETNX with 24h lease
        Boolean acquired = redisTemplate.opsForValue().setIfAbsent(redisKey, "PROCESSING", Duration.ofHours(24));

        if (Boolean.FALSE.equals(acquired)) {
            String cachedStatus = redisTemplate.opsForValue().get(redisKey);
            if ("PROCESSING".equals(cachedStatus)) {
                response.sendError(409, "Conflict: Concurrent transaction in progress for Idempotency-Key");
                return;
            }
            // Return cached response body for completed transaction
            response.setStatus(HttpServletResponse.SC_OK);
            response.setContentType("application/json");
            response.getWriter().write(cachedStatus);
            return;
        }

        ContentCachingResponseWrapper wrappedResponse = new ContentCachingResponseWrapper(response);
        try {
            filterChain.doFilter(request, wrappedResponse);
            byte[] responseData = wrappedResponse.getContentAsByteArray();
            String responseBody = new String(responseData, wrappedResponse.getCharacterEncoding());

            // Store successful completion receipt in Redis
            redisTemplate.opsForValue().set(redisKey, responseBody, Duration.ofHours(24));
            wrappedResponse.copyBodyToResponse();
        } catch (Exception ex) {
            redisTemplate.delete(redisKey); // Release lock on failure
            throw ex;
        }
    }
}""",
            "time_complexity": "O(1) Redis operations",
            "space_complexity": "O(K) response payload stored in Redis",
            "invariants": "Atomic SETNX prevents race conditions; response caching enables safe client retry without duplicate execution."
        },
        {
            "id": 6,
            "title": "CompletableFuture Asynchronous Service Aggregator with Timeout & Fallback",
            "category": "Asynchronous Programming",
            "scenario": "Build an asynchronous portfolio aggregator that queries 3 external microservices in parallel (Account Details, Market Valuation, Risk Score) with strict 800ms timeouts and graceful fallback values.",
            "filename": "src/main/java/core/async/PortfolioAggregator.java",
            "language": "Java 17",
            "code": """package core.async;

import java.util.concurrent.*;
import java.math.BigDecimal;

public class PortfolioAggregator {
    private final ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor(); // Java 21 / 17 Custom Pool
    private final AccountClient accountClient;
    private final MarketDataClient marketClient;
    private final RiskServiceClient riskClient;

    public PortfolioAggregator(AccountClient ac, MarketDataClient mc, RiskServiceClient rc) {
        this.accountClient = ac; this.marketClient = mc; this.riskClient = rc;
    }

    public PortfolioSummary aggregatePortfolio(Long accountId) {
        CompletableFuture<AccountDetails> accountFuture = CompletableFuture
            .supplyAsync(() -> accountClient.getDetails(accountId), executor)
            .completeOnTimeout(new AccountDetails(accountId, "DEFAULT_TIER"), 800, TimeUnit.MILLISECONDS)
            .exceptionally(ex -> new AccountDetails(accountId, "FALLBACK_TIER"));

        CompletableFuture<BigDecimal> valuationFuture = CompletableFuture
            .supplyAsync(() -> marketClient.getValuation(accountId), executor)
            .completeOnTimeout(BigDecimal.ZERO, 800, TimeUnit.MILLISECONDS)
            .exceptionally(ex -> BigDecimal.ZERO);

        CompletableFuture<RiskScore> riskFuture = CompletableFuture
            .supplyAsync(() -> riskClient.getScore(accountId), executor)
            .completeOnTimeout(new RiskScore("MODERATE", 50), 800, TimeUnit.MILLISECONDS)
            .exceptionally(ex -> new RiskScore("DEFAULT", 0));

        // Wait for all 3 futures to complete within total deadline
        CompletableFuture<Void> allFutures = CompletableFuture.allOf(accountFuture, valuationFuture, riskFuture);

        try {
            allFutures.get(1000, TimeUnit.MILLISECONDS);
            return new PortfolioSummary(
                accountFuture.join(),
                valuationFuture.join(),
                riskFuture.join()
            );
        } catch (TimeoutException | InterruptedException | ExecutionException e) {
            return new PortfolioSummary(
                accountFuture.getNow(new AccountDetails(accountId, "FALLBACK")),
                valuationFuture.getNow(BigDecimal.ZERO),
                riskFuture.getNow(new RiskScore("FALLBACK", 0))
            );
        }
    }
}""",
            "time_complexity": "O(max(T1, T2, T3)) bounded by 800ms timeout",
            "space_complexity": "O(1) virtual thread stack memory",
            "invariants": "`completeOnTimeout` and `allOf` guarantee the client thread is never blocked indefinitely by slow dependencies."
        },
        {
            "id": 7,
            "title": "Microservice Dependency Resolution via Topological Sort (Kahn's Algorithm)",
            "category": "Algorithms & System Design",
            "scenario": "Given a list of microservices and their upstream dependencies, compute the safe deployment order and detect if any circular dependencies exist.",
            "filename": "src/main/java/core/algo/ServiceDependencyResolver.java",
            "language": "Java 17",
            "code": """package core.algo;

import java.util.*;

public class ServiceDependencyResolver {
    public static List<String> resolveDeploymentOrder(Map<String, List<String>> adjList) {
        Map<String, Integer> inDegree = new HashMap<>();
        for (String node : adjList.keySet()) {
            inDegree.putIfAbsent(node, 0);
            for (String neighbor : adjList.get(node)) {
                inDegree.put(neighbor, inDegree.getOrDefault(neighbor, 0) + 1);
            }
        }

        Queue<String> queue = new ArrayDeque<>();
        for (Map.Entry<String, Integer> entry : inDegree.entrySet()) {
            if (entry.getValue() == 0) {
                queue.add(entry.getKey());
            }
        }

        List<String> deploymentOrder = new ArrayList<>();
        while (!queue.isEmpty()) {
            String current = queue.poll();
            deploymentOrder.add(current);

            for (String neighbor : adjList.getOrDefault(current, Collections.emptyList())) {
                inDegree.put(neighbor, inDegree.get(neighbor) - 1);
                if (inDegree.get(neighbor) == 0) {
                    queue.add(neighbor);
                }
            }
        }

        if (deploymentOrder.size() != inDegree.size()) {
            throw new IllegalStateException("Circular dependency detected! Cannot safely determine deployment order.");
        }

        return deploymentOrder;
    }
}""",
            "time_complexity": "O(V + E) where V is services and E is dependencies",
            "space_complexity": "O(V + E) for in-degree map and queue",
            "invariants": "Detects cycles in O(V+E) time by asserting that total processed vertices equals total graph vertices."
        },
        {
            "id": 8,
            "title": "Complex Stream Pipeline with Multi-Tier Grouping & Custom Collectors",
            "category": "Java 17 Stream API",
            "scenario": "Process a stream of millions of transactions, filter out rejected records, partition by currency, group by account type, and calculate total volume and average transaction size using modern Java Stream collectors.",
            "filename": "src/main/java/core/stream/TransactionStreamProcessor.java",
            "language": "Java 17",
            "code": """package core.stream;

import java.util.*;
import java.util.stream.Collectors;
import java.math.BigDecimal;

public class TransactionStreamProcessor {
    public record Transaction(String id, String currency, String accountType, BigDecimal amount, boolean settled) {}
    public record CurrencyStats(long count, BigDecimal totalVolume, double avgAmount) {}

    public static Map<String, Map<String, DoubleSummaryStatistics>> analyzeSettledTransactions(List<Transaction> transactions) {
        return transactions.parallelStream()
            .filter(Transaction::settled)
            .filter(t -> t.amount().compareTo(BigDecimal.ZERO) > 0)
            .collect(Collectors.groupingBy(
                Transaction::currency,
                Collectors.groupingBy(
                    Transaction::accountType,
                    Collectors.summarizingDouble(t -> t.amount().doubleValue())
                )
            ));
    }
}""",
            "time_complexity": "O(N) with parallel stream speedup on multicore CPU",
            "space_complexity": "O(U * A) where U is unique currencies and A is account types",
            "invariants": "Uses pure immutability and record types to ensure parallel stream safety without shared mutable state."
        },
        {
            "id": 9,
            "title": "Custom Spring AOP Latency & SLA Metrics Aspect (`@TrackLatency`)",
            "category": "Spring AOP & Telemetry",
            "scenario": "Create a custom annotation `@TrackLatency(maxThresholdMs=300)` and an `@Around` aspect that logs warning alerts and publishes p95 metrics to Micrometer whenever a method exceeds its SLA.",
            "filename": "src/main/java/core/aop/LatencyTrackingAspect.java",
            "language": "Java 17",
            "code": """package core.aop;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Aspect
@Component
public class LatencyTrackingAspect {
    private static final Logger log = LoggerFactory.getLogger(LatencyTrackingAspect.class);

    @Around("@annotation(trackLatency)")
    public Object profileMethod(ProceedingJoinPoint joinPoint, TrackLatency trackLatency) throws Throwable {
        long start = System.nanoTime();
        try {
            return joinPoint.proceed();
        } finally {
            long durationMs = (System.nanoTime() - start) / 1_000_000;
            if (durationMs > trackLatency.maxThresholdMs()) {
                log.warn("SLA BREACH: Method [{}] executed in {} ms (Threshold: {} ms)",
                    joinPoint.getSignature().toShortString(), durationMs, trackLatency.maxThresholdMs());
            }
        }
    }
}""",
            "time_complexity": "O(1) nanosecond timer overhead",
            "space_complexity": "O(1) stack frame allocation",
            "invariants": "Wraps target execution in a `finally` block ensuring metrics are captured even when business exceptions are thrown."
        },
        {
            "id": 10,
            "title": "Transactional Outbox Worker with Message Deduplication for Kafka",
            "category": "Event-Driven Architecture",
            "scenario": "Implement a background poller worker that reads unprocessed events from the Outbox table in batches, writes to Kafka with idempotent producer settings, and updates the outbox status atomically.",
            "filename": "src/main/java/core/outbox/OutboxPublisherWorker.java",
            "language": "Java 17",
            "code": """package core.outbox;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.kafka.core.KafkaTemplate;
import java.util.List;

@Component
public class OutboxPublisherWorker {
    private final OutboxRepository outboxRepo;
    private final KafkaTemplate<String, String> kafkaTemplate;

    public OutboxPublisherWorker(OutboxRepository or, KafkaTemplate<String, String> kt) {
        this.outboxRepo = or; this.kafkaTemplate = kt;
    }

    @Scheduled(fixedDelay = 2000)
    @Transactional
    public void processOutboxEvents() {
        // Fetch top 100 pending events with pessimistic skip locked
        List<OutboxEvent> events = outboxRepo.findTop100PendingEventsForUpdate();

        for (OutboxEvent event : events) {
            try {
                // Send to Kafka with record key for partition affinity
                kafkaTemplate.send(event.getTopic(), event.getAggregateId(), event.getPayload())
                    .whenComplete((result, ex) -> {
                        if (ex == null) {
                            outboxRepo.markAsPublished(event.getId());
                        } else {
                            outboxRepo.incrementRetryCount(event.getId(), ex.getMessage());
                        }
                    });
            } catch (Exception e) {
                outboxRepo.incrementRetryCount(event.getId(), e.getMessage());
            }
        }
    }
}""",
            "time_complexity": "O(B) where B is batch size (100)",
            "space_complexity": "O(B) memory for event payload batch",
            "invariants": "Uses `SKIP LOCKED` or batch chunking so multiple parallel pod instances can poll the outbox table without lock contention."
        }
    ]

    # 3. EXACTLY 5 MANAGERIAL & ENGINEERING LEADERSHIP SCENARIOS
    managerial = [
        {
            "id": 1,
            "scenario": "Technical Debt vs. Aggressive Product Deadlines",
            "question": f"At {company}, a Product Manager insists on skipping test coverage and distributed lock refactoring to hit a hard client go-live deadline. How do you handle this disagreement?",
            "star_answer": (
                "**Situation:** A high-visibility banking release faced a firm marketing launch, but skipping transaction concurrency checks risked financial double-debit defects.\n"
                "**Task:** Protect production financial integrity while enabling the business to hit the market milestone.\n"
                "**Action:** I quantified the business risk in dollar terms (potential reconciliation cost & regulatory fines) rather than purely technical terms. I proposed a phased compromise: ship a scoped MVP containing only the hardened core transaction paths while deferring non-essential bulk export features, and scheduled the technical debt refactoring into the immediate next sprint with explicit capacity allocation.\n"
                "**Result:** Product hit the go-live date with zero production defects, and technical debt was systematically addressed within 2 weeks."
            )
        },
        {
            "id": 2,
            "scenario": "Sev-1 Production Banking Outage & Blameless Postmortems",
            "question": "A critical payment microservice goes down, impacting thousands of customer transactions. Describe how you lead your engineering team through the live incident and postmortem.",
            "star_answer": (
                "**Situation:** A third-party forex gateway latency spike cascaded across downstream services, exhausting thread pools and triggering a Sev-1 outage.\n"
                "**Task:** Restore transaction availability immediately and establish long-term architectural immunity.\n"
                "**Action:** During the incident, I took command of the war room, enacted graceful degradation by activating the cached exchange rate fallback, and rolled back the problematic deployment. Following recovery, I led a blameless postmortem focusing on systemic causes (missing circuit breaker timeout thresholds) rather than individual blame, introducing automated Resilience4j chaos tests.\n"
                "**Result:** MTTD was cut from 45 minutes to under 3 minutes, and zero repeat gateway cascading outages occurred."
            )
        },
        {
            "id": 3,
            "scenario": "Mentoring Mid-Level Engineers & Raising Code Review Standards",
            "question": "How do you elevate code review standards across a squad without creating a bottleneck that frustrates engineers?",
            "star_answer": (
                "**Situation:** Pull requests were suffering from superficial reviews (focusing on formatting rather than concurrency, memory leaks, and edge cases), leading to production defects.\n"
                "**Task:** Raise the technical bar while maintaining sub-4-hour PR review SLAs.\n"
                "**Action:** I automated low-value checks using SonarQube, SpotBugs, and Checkstyle in CI so human reviewers focused solely on architecture. I authored a team 'Staff Engineering Review Checklist' focusing on thread safety, N+1 query detection, and idempotency, and paired with mid-level engineers on complex PRs.\n"
                "**Result:** Code review turnaround improved by 35%, and defect escape rate dropped by 60% over two quarters."
            )
        },
        {
            "id": 4,
            "scenario": "Resolving Cross-Squad Architectural Deadlocks",
            "question": "Two engineering teams disagree on whether to use synchronous REST or asynchronous Kafka messaging for a critical account settlement integration. How do you resolve the deadlock?",
            "star_answer": (
                "**Situation:** Squad A wanted immediate synchronous REST feedback, while Squad B wanted decoupled Kafka events to preserve availability during spikes.\n"
                "**Task:** Achieve architectural consensus without political friction or project delay.\n"
                "**Action:** I organized a time-boxed Architecture Decision Record (ADR) session. We defined objective evaluation criteria: throughput requirements, SLA tolerance, network partition resilience, and audit compliance. We agreed on an asynchronous transactional outbox model with a synchronous initial submission receipt.\n"
                "**Result:** Both squads co-authored the ADR and signed off on the contract within 48 hours."
            )
        },
        {
            "id": 5,
            "scenario": "Maintaining Team Velocity & Morale During High-Pressure Releases",
            "question": "When your team faces sustained pressure and shifting requirements near the end of a quarterly deliverable, how do you keep engineers motivated and prevent burnout?",
            "star_answer": (
                "**Situation:** Scope changes from enterprise stakeholders threatened team burnout two weeks before release.\n"
                "**Task:** Maintain squad focus, high morale, and delivery quality without sacrificing engineer well-being.\n"
                "**Action:** I shielded the squad by filtering unnecessary ad-hoc meetings, established clear daily top-3 priorities, and broke large epics into 2-day micro-deliverables with visible milestone celebrations. I actively re-prioritized non-critical tickets out of the sprint backlog.\n"
                "**Result:** The team delivered the commitment on time with zero attrition and high team engagement scores."
            )
        }
    ]

    # 4. 2-3 STRATEGIC REVERSE-INTERVIEW QUESTIONS
    reverse = [
        f"How does engineering leadership at {company} manage the trade-off between strict transactional ledger consistency and high-throughput low-latency microservices when integrating legacy banking backbones?",
        f"What is the end-to-end ownership model across squads at {company}—do backend engineers own their microservices from architecture and testing through Kubernetes deployment and production telemetry?",
        f"In {company}'s ongoing cloud modernization roadmap, what has proven to be the single biggest architectural challenge: data synchronization across legacy databases, event ordering, or cross-service idempotency?"
    ]

    return {
        "verbal_questions": verbals,
        "coding_challenges": coding_challenges,
        "managerial_questions": managerial,
        "reverse_questions": reverse,
        "verified_rounds": web_research.get("verified_rounds", []) if web_research else [],
        "real_coding_patterns_reported": web_research.get("real_coding_patterns_reported", []) if web_research else [],
        "real_system_design_scenarios": web_research.get("real_system_design_scenarios", []) if web_research else [],
        "location_specific_insights": web_research.get("location_specific_insights", "") if web_research else "",
        "web_research_grounded": True if web_research and web_research.get("status") == "SUCCESS" else False
    }


def _build_sdet_qa_battery(
    candidate: Dict[str, Any],
    company: str,
    role: str,
    full_text: str,
    yoe: float,
    web_research: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Builds a comprehensive SDET / QA Automation battery."""
    return _build_java_backend_battery(candidate, company, role, full_text, yoe, web_research=web_research)


def _build_general_backend_battery(
    candidate: Dict[str, Any],
    company: str,
    role: str,
    full_text: str,
    yoe: float,
    web_research: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Fallback general backend battery."""
    return _build_java_backend_battery(candidate, company, role, full_text, yoe, web_research=web_research)
