"""只读审计新版前端 submitlice 的触发源码；禁止保存和最终送审。"""

from pathlib import Path
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.browser import BrowserConfig, BrowserSession
from src.input_loader import load_input
from src.new_audit_qualification import NewAuditQualificationPage
from src.run_logging import application_data_dir
from src.workflow import WorkflowConfig, WorkflowRunner


class SubmitTriggerInspector(WorkflowRunner):
    def _run_industry_qualification(self, page, company):
        view = NewAuditQualificationPage(page, timeout=60_000)
        add = view._wait_for_unique_visible(
            page.get_by_role("button", name="新增资质", exact=True),
            "新增资质",
            timeout=60_000,
        )
        add.click()
        view._wait_until(view._is_new_audit_add_page, "新增页未加载", timeout=60_000)
        if not view._business_tabs():
            view._unique_visible(view._add_business_buttons(), "新增业务资质").click()
            view._wait_until(lambda: bool(view._business_tabs()), "业务表单未加载")

        result = page.evaluate("""async () => {
          const output = [];
          const resources = [...new Set(performance.getEntriesByType('resource')
            .map(item => item.name).filter(name => /\\.js(?:\\?|$)/.test(name)))];
          const keywords = [
            'handleMouseLeave', 'isCallSubmitApi', 'handleSubmit',
            'submitLice', 'document.hasFocus', 'manageType'
          ];
          for (const resource of resources) {
            try {
              const response = await fetch(resource.split('?')[0] + '.map');
              if (!response.ok) continue;
              const sourceMap = await response.json();
              for (let i = 0; i < (sourceMap.sourcesContent || []).length; i++) {
                const source = sourceMap.sourcesContent[i] || '';
                if (!source.includes('submitLice')
                    && !source.includes('savelicepic')
                    && !source.includes("emit('uploaded'")
                    && !source.includes('changeEvidenceFile')
                    && !String(sourceMap.sources[i]).includes('AddReserveLice')) continue;
                const snippets = [];
                for (const keyword of keywords) {
                  let start = 0;
                  while (true) {
                    const position = source.indexOf(keyword, start);
                    if (position < 0) break;
                    snippets.push({
                      keyword,
                      text: source.slice(Math.max(0, position - 900), position + 1800),
                    });
                    start = position + keyword.length;
                  }
                }
                output.push({source: sourceMap.sources[i], content: source, snippets});
              }
            } catch (_) {}
          }
          return output;
        }""")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return False, False, None


def main():
    company = next(
        company for company in load_input(Path("input"))
        if company.company_name == "东莞山虞医药有限公司"
    )
    config = BrowserConfig(
        auth_state_path=application_data_dir() / "auth" / "storage_state.json"
    )
    with BrowserSession(config) as session:
        session.context.route(
            re.compile(r"/permit/web/permit/(?:submitlice|submitall)(?:[?#]|$)"),
            lambda route: route.abort(),
        )
        SubmitTriggerInspector(
            session, WorkflowConfig(final_submit=False, page_timeout_ms=60_000)
        ).run_company(company)


if __name__ == "__main__":
    main()
