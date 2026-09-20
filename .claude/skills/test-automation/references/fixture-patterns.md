# 통합 테스트 픽스처 패턴 (언어별 스니펫)

테스트 생성 시 그대로 응용할 수 있는 최소 패턴입니다. 공통 원칙: **테스트마다 깨끗한 상태**, **외부 실서비스 차단**,
**응답 + 상태 변화를 함께 단언**.

## Python — pytest

### FastAPI + SQLAlchemy: 테스트마다 롤백되는 DB 세션 + 앱 클라이언트

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, get_db

# 임시 SQLite (파일 기반이면 여러 커넥션에서도 동일 DB를 본다)
engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    # 테스트마다 트랜잭션을 열고 끝나면 롤백 → 테스트 간 격리
    conn = engine.connect()
    tx = conn.begin()
    session = TestingSession(bind=conn)
    yield session
    session.close()
    tx.rollback()
    conn.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

```python
# tests/integration/test_orders.py
def test_create_order_persists_and_returns_201(client, db):
    res = client.post("/orders", json={"item_id": 1, "qty": 2})
    assert res.status_code == 201
    # 응답뿐 아니라 DB 상태까지 확인
    from app.models import Order
    assert db.query(Order).filter_by(id=res.json()["id"]).one().qty == 2


def test_create_order_rolls_back_when_payment_fails(client, db, monkeypatch):
    # 외부 결제 API 실패 주입
    from app import payments
    monkeypatch.setattr(payments, "charge", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    res = client.post("/orders", json={"item_id": 1, "qty": 2})
    assert res.status_code == 502
    from app.models import Order
    assert db.query(Order).count() == 0  # 부분 저장이 없어야 한다
```

### 외부 HTTP 목: `respx`(httpx) / `responses`(requests)

```python
import respx, httpx

@respx.mock
def test_calls_inventory_service_with_timeout_handling(client):
    respx.get("https://inventory.internal/stock/1").mock(side_effect=httpx.TimeoutException("t/o"))
    res = client.get("/items/1/availability")
    assert res.status_code == 503
```

### testcontainers (PostgreSQL)

```python
import pytest
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def pg_url():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()
```

Docker가 없으면 이 픽스처는 실패합니다 → "환경 문제"로 분류하고 SQLite 대체 여부를 레포트에 명시.

## JavaScript / TypeScript — Jest/Vitest + supertest

```ts
// tests/integration/orders.spec.ts
import request from "supertest";
import { createApp } from "../../src/app";
import { db, migrate, truncateAll } from "../../src/db";

let app: ReturnType<typeof createApp>;

beforeAll(async () => {
  process.env.DATABASE_URL = "sqlite::memory:";   // 또는 testcontainers
  await migrate();
  app = createApp();
});
beforeEach(async () => { await truncateAll(); });   // 테스트마다 초기화
afterAll(async () => { await db.destroy(); });

test("POST /orders → 201 이고 DB 에 저장된다", async () => {
  const res = await request(app).post("/orders").send({ itemId: 1, qty: 2 });
  expect(res.status).toBe(201);
  const row = await db("orders").where({ id: res.body.id }).first();
  expect(row.qty).toBe(2);
});

test("결제 실패 시 502 + 주문 미저장", async () => {
  jest.spyOn(require("../../src/payments"), "charge").mockRejectedValue(new Error("timeout"));
  const res = await request(app).post("/orders").send({ itemId: 1, qty: 2 });
  expect(res.status).toBe(502);
  expect(await db("orders").count().first()).toMatchObject({ "count(*)": 0 });
});
```

- 외부 HTTP 목: `nock` (Node) 또는 `msw`.
- Vitest는 `jest.spyOn` 대신 `vi.spyOn`, 결과는 `--reporter=junit`으로 수집됩니다(러너가 자동 지정).

## Java / Kotlin — JUnit 5 + Spring Boot + Testcontainers

```java
@SpringBootTest
@AutoConfigureMockMvc
@Testcontainers
class OrderIntegrationTest {

    @Container
    static PostgreSQLContainer<?> pg = new PostgreSQLContainer<>("postgres:16-alpine");

    @DynamicPropertySource
    static void props(DynamicPropertyRegistry r) {
        r.add("spring.datasource.url", pg::getJdbcUrl);
        r.add("spring.datasource.username", pg::getUsername);
        r.add("spring.datasource.password", pg::getPassword);
    }

    @Autowired MockMvc mvc;
    @Autowired OrderRepository orders;
    @MockBean PaymentClient payment;   // 외부 결제 API 차단

    @BeforeEach void clean() { orders.deleteAll(); }

    @Test
    void createOrder_persists() throws Exception {
        mvc.perform(post("/orders").contentType(APPLICATION_JSON).content("{\"itemId\":1,\"qty\":2}"))
           .andExpect(status().isCreated());
        assertThat(orders.count()).isEqualTo(1);
    }

    @Test
    void createOrder_rollsBack_whenPaymentFails() throws Exception {
        when(payment.charge(any())).thenThrow(new PaymentTimeoutException());
        mvc.perform(post("/orders").contentType(APPLICATION_JSON).content("{\"itemId\":1,\"qty\":2}"))
           .andExpect(status().isBadGateway());
        assertThat(orders.count()).isZero();
    }
}
```

- Maven: 통합 테스트는 `*IT.java` + failsafe 플러그인, 또는 surefire에 포함. 러너는 두 리포트 모두 집계합니다.
- Docker 없으면 H2(`spring.datasource.url=jdbc:h2:mem:test`)로 대체하고 레포트에 명시.

## Go — httptest

```go
func newTestServer(t *testing.T) (*httptest.Server, *sql.DB) {
    db, _ := sql.Open("sqlite", ":memory:")
    migrate(t, db)
    srv := httptest.NewServer(NewRouter(db, fakePayment{fail: false}))
    t.Cleanup(func() { srv.Close(); db.Close() })
    return srv, db
}

func TestCreateOrder_Persists(t *testing.T) {
    srv, db := newTestServer(t)
    res, _ := http.Post(srv.URL+"/orders", "application/json", strings.NewReader(`{"item_id":1,"qty":2}`))
    if res.StatusCode != 201 { t.Fatalf("status=%d", res.StatusCode) }
    var n int
    db.QueryRow("select count(*) from orders").Scan(&n)
    if n != 1 { t.Fatalf("orders=%d", n) }
}
```

## 공통 체크

- 시간 의존: `datetime.now()`/`Date.now()`는 주입/고정(freezegun, `jest.useFakeTimers`).
- 순서 의존: 테스트 간 공유 상태 금지. 병렬 실행에도 안전해야 함.
- 실패 시나리오는 **예외가 삼켜지지 않는지**(로그만 찍고 200을 주는지)까지 확인.
