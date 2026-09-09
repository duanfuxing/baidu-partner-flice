"""诊断新版举证链接的真实自动保存触发事件；绝不触发最终送审。"""

from pathlib import Path
from urllib.parse import urlsplit
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser import BrowserConfig, BrowserSession
from src.input_loader import load_input
from src.new_audit_qualification import (
    NewAuditQualificationPage,
    SUBMITLICE_PATH,
    is_permit_post_response,
)
from src.run_logging import application_data_dir
from src.workflow import WorkflowConfig, WorkflowRunner


class EvidenceSaveInspector(WorkflowRunner):
    def _run_industry_qualification(self, page, company):
        page.get_by_text("已备案业务资质", exact=True).click(timeout=30_000)
        page.wait_for_timeout(1_000)
        rows = [
            row for row in NewAuditQualificationPage._visible(page.locator("tr"))
            if row.get_by_text("推广审查", exact=True).count()
            and row.get_by_text("已保存待送审", exact=True).count()
        ]
        if len(rows) != 1:
            raise RuntimeError(f"Expected one saved promotion row, got {len(rows)}")
        rows[0].get_by_role("button", name="修改", exact=True).click()
        page.get_by_text("编辑投放资质", exact=True).wait_for(
            state="visible", timeout=30_000
        )
        view = NewAuditQualificationPage(page, timeout=60_000)
        file_input = page.locator('input[type="file"]').first
        file_input.wait_for(state="attached", timeout=30_000)
        form = view._upload_container(file_input)
        evidence = view._unique_visible(
            form.locator('input:not([type="file"])'), "首张举证链接输入框"
        )
        expected = next(
            q.evidence_url
            for t in company.qualification_types if t.type_name == "推广审查"
            for q in t.qualifications if q.files
        ) or ""

        ancestors = evidence.evaluate("""element => {
          const result = [];
          for (let node = element; node && result.length < 30; node = node.parentElement) {
            const props = node.__vueParentComponent?.vnode?.props || {};
            const vei = node._vei || {};
            const vue2 = node.__vue__ || {};
            result.push({
              tag: node.tagName,
              className: String(node.className || '').slice(0, 160),
              vueEvents: Object.keys(props).filter(key => /^on[A-Z]/.test(key)),
              nativeEvents: Object.keys(vei),
              vue2Events: Object.keys(vue2.$listeners || {}),
              component: node.__vueParentComponent?.type?.name ||
                node.__vueParentComponent?.type?.__name || vue2.$options?.name || '',
            });
          }
          return result;
        }""")
        print("ANCESTORS", ancestors, flush=True)
        print("UPLOAD_CONTAINER_CLASS", form.get_attribute("class"), flush=True)
        print("DOCUMENT_FOCUS", page.evaluate("document.hasFocus()"), flush=True)
        bundle_snippets = page.evaluate("""async () => {
          const result = [];
          const names = [...new Set(performance.getEntriesByType('resource')
            .map(item => item.name).filter(name => /\\.js(?:\\?|$)/.test(name)))];
          for (const name of names) {
            try {
              if (!name.includes('AddReserveLice')) continue;
              const sourceMap = await (await fetch(name.split('?')[0] + '.map')).json();
              for (let index = 0; index < sourceMap.sourcesContent.length; index++) {
                const source = sourceMap.sourcesContent[index] || '';
                if (!source.includes('submitLice') && !source.includes('鼠标移出当前卡片')) continue;
                for (const keyword of [
                  'const handleSubmit', 'const handleMouseLeave', 'const isMain',
                  'const formatFormData', 'isCallSubmitApi'
                ]) {
                  const needle = source.indexOf(keyword);
                  if (needle >= 0) result.push({
                    file: sourceMap.sources[index], keyword,
                    snippet: source.slice(Math.max(0, needle - 1800), needle + 3200),
                  });
                }
              }
            } catch (_) {}
          }
          return result;
        }""")
        print("SUBMITLICE_BUNDLES", bundle_snippets, flush=True)
        return False, False, None

        responses = []

        def record(response):
            if is_permit_post_response(response, SUBMITLICE_PATH):
                try:
                    payload = response.json()
                except Exception:
                    payload = None
                responses.append((response.status, payload.get("status") if isinstance(payload, dict) else None))

        page.on("response", record)
        page.bring_to_front()
        page.evaluate("window.focus()")
        print("DOCUMENT_FOCUS_AFTER_BRING_TO_FRONT", page.evaluate("document.hasFocus()"), flush=True)
        evidence.click()
        evidence.fill(expected)
        actions = (
            ("tab", lambda: evidence.press("Tab")),
            ("change", lambda: evidence.dispatch_event("change")),
            ("enter", lambda: evidence.press("Enter")),
            ("exact-form-card-mouseleave", lambda: (
                evidence.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' form-card ')][1]").hover(),
                page.wait_for_timeout(300), page.mouse.move(0, 0)
            )),
            ("page-header-click", view._click_outside_qualification_card),
        )
        previous = 0
        for name, action in actions:
            action()
            page.wait_for_timeout(3_000)
            print("ACTION", name, "NEW_RESPONSES", responses[previous:], flush=True)
            if len(responses) > previous:
                break
            previous = len(responses)
        current = view._unique_visible(
            view._upload_container(page.locator('input[type="file"]').first).locator(
                'input:not([type="file"])'
            ),
            "刷新后的首张举证链接输入框",
        )
        print("FINAL_VALUE_MATCH", current.input_value().strip() == expected, flush=True)
        print("FINAL_RESPONSE_COUNT", len(responses), flush=True)
        print("FINAL_HOST", urlsplit(page.url).hostname, flush=True)
        return False, False, None


def main():
    company = next(
        c for c in load_input(Path("input"))
        if c.company_name == "东莞山虞医药有限公司"
    )
    config = BrowserConfig(
        auth_state_path=application_data_dir() / "auth" / "storage_state.json"
    )
    with BrowserSession(config) as session:
        session.context.route(
            "**/permit/web/permit/submitall", lambda route: route.abort()
        )
        EvidenceSaveInspector(
            session, WorkflowConfig(final_submit=False, page_timeout_ms=60_000)
        ).run_company(company)


if __name__ == "__main__":
    main()
