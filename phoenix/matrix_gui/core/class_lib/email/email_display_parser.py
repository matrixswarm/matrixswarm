from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton
from PyQt6.QtCore import Qt
import html
import json


class EmailDisplayParser(QDialog):
    """
    A reusable popup dialog to display a parsed email with formatted HTML content.
    """

    def __init__(self, parent=None, title="📧 Parsed Email", data=None):
        """
        Initialize the dialog.

        :param parent: The parent widget (usually the main window or session).
        :param title: The title of the dialog window.
        :param data: The structured data to be rendered (optional; can also load later via `render_data`).
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(800, 600)

        # Set the dialog to behave independently of other windows
        self.setWindowFlag(Qt.WindowType.Window)

        # Layout setup
        layout = QVBoxLayout()

        # Add a QTextBrowser for display
        self.text_browser = QTextBrowser(self)
        layout.addWidget(self.text_browser)

        # Close button
        self.close_btn = QPushButton("Close", self)
        self.close_btn.clicked.connect(self.close_popup)
        layout.addWidget(self.close_btn)

        # Apply layout
        self.setLayout(layout)

        # Optionally render data passed during initialization
        if data:
            self.render_data(data)

    def generate_html(self, data):
        """
        Generate HTML for email rendering (used by both inline and popup display).
        Returns the HTML string for insertion elsewhere.
        """
        try:
            def section(title, value, color="#8ec07c"):
                if not value:
                    return ""
                escaped = html.escape(str(value))
                return f"""
                <div style='margin-top:10px;'>
                  <input type="checkbox" id="{title}" style="display:none;">
                  <label for="{title}" style="font-weight:bold; color:{color}; cursor:pointer; margin-bottom:4px;">
                    ▶ {title}
                  </label>
                  <div style="margin-top:4px; display:none; background:#1a1a1a; padding:8px;
                              border-left:3px solid {color}; border-radius:4px;"
                       class="collapsible">
                    <pre style='color:#ccc; margin:0; white-space:pre-wrap;'>{escaped}</pre>
                  </div>
                </div>
                """

            html_out = f"""
            <html>
            <head>
            <style>
              body {{
                font-family: Consolas, monospace;
                font-size: 13px;
                color: #ccc;
                background: #0d0d0d;
                padding: 10px;
                line-height: 1.4;
              }}
              h3 {{
                color: #4ec9b0;
                border-bottom: 1px solid #333;
                padding-bottom: 4px;
              }}
              label:hover {{
                text-decoration: underline;
              }}
              input:checked + label + .collapsible {{
                display: block;
              }}
            </style>
            </head>
            <body>
              <h3>📧 Parsed Email</h3>
              {section("From", data.get("from"), "#00ffff")}
              {section("To", data.get("to"), "#00ffff")}
              {section("Subject", data.get("subject"), "#00ff99")}
              {section("Date", data.get("date"), "#ccccff")}
              {section("Headers", data.get("headers"), "#ffaa00")}
              {section("Body (Text)", data.get("body_text") or "", "#ffffff")}
            """

            if data.get("body_html"):
                escaped_html = html.escape(data["body_html"])
                html_out += section("Body (HTML)", escaped_html, "#ffcc00")

            if data.get("attachments"):
                html_out += "<h4 style='color:#ff9966; margin-top:14px;'>📎 Attachments</h4>"
                for att in data["attachments"]:
                    html_out += f"<pre style='color:#888;'>{html.escape(json.dumps(att, indent=2))}</pre>"

            html_out += "</body></html>"
            return html_out
        except Exception as e:
            return f"<pre style='color:red;'>[ERROR generating HTML] {e}</pre>"

    def render_data(self, data):
        """Render structured data into formatted HTML content."""
        try:
            html_out = self.generate_html(data)
            self.text_browser.setHtml(html_out)
        except Exception as e:
            self.text_browser.setPlainText(f"[ERROR displaying data] {e}")

    def close_popup(self):
        """
        Handle the close button action safely.
        """
        print("DEBUG: Closing EmailDisplayParser dialog.")
        self.close()

    def closeEvent(self, event):
        """
        Handle dialog closure and ensure proper cleanup.
        """
        print("DEBUG: EmailDisplayParser dialog closed.")
        super().closeEvent(event)
