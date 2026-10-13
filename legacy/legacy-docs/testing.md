# Testing Guide

在開發與更改模組後，應將自動化測試補上並驗證其正確性。可以使用 Django 內建的 Unittest 框架與 Docker Compose 環境。

## 建立與管理測試檔案

1. **檔案位置**：每個 App 應有專屬的 `tests.py`。
   - `apps/accounts/tests.py`
   - `apps/subscriptions/tests.py`
2. **測試範圍**：針對各 App，你可以在同一個檔案內定義不同類別，分別測試：
   - Models (與其 Constraints)
   - Serializers (請求參數進出的校驗)
   - API Views (權限、Responses)

---

## 如何執行 Unit Tests

這會自動建立一個暫時的空白資料庫，套用已有的 Migrations 並執行所有測試，執行完畢後會被銷毀，不會影響現存的資料庫環境。

### 1. 執行單個 App 中所有的完整測試

```bash
sudo docker compose exec web python manage.py test apps.subscriptions
```

### 2. 測試特定 App 內的特定類別或方法
如果你目前只想確認剛剛寫的某一個測試是否通過，可以在後面加上完整的路徑。

```bash
# 只執行單一類別的測試
sudo docker compose exec web python manage.py test apps.subscriptions.tests.SubscriptionModelsTest

# 只執行類別中某單支特定的 function
sudo docker compose exec web python manage.py test apps.subscriptions.tests.SubscriptionModelsTest.test_invalid_alias_name
```

---

## 常見錯誤

如果執行上述指令時遇到模組無法加載或是路徑解析的錯誤（e.g., `ModuleNotFoundError` 或是 `TypeError`），請檢查：

1. `apps/` 根目錄底下必須具備空白的 `__init__.py` 檔案，這樣 Python 才會將其認定為 valid module。
2. 在 `core/settings.py` 中的 `INSTALLED_APPS` 內，你必須透過明確的 `AppConfig` 進行註冊，例如：
   - `apps.subscriptions.apps.SubscriptionsConfig`
