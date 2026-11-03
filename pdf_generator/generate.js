const fs = require('fs');
const puppeteer = require('puppeteer');
const { marked } = require('marked');

async function generate() {
    const mdPath = '/Users/aarsh/.gemini/antigravity/brain/e0cb5c9d-80ae-450e-a7eb-db79b1adad07/MediKiosk_SIH_Report.md';
    const pdfPath = '/Users/aarsh/.gemini/antigravity/brain/e0cb5c9d-80ae-450e-a7eb-db79b1adad07/MediKiosk_SIH_Report.pdf';
    
    const mdContent = fs.readFileSync(mdPath, 'utf8');
    
    // Customize marked to parse markdown
    const htmlContent = marked.parse(mdContent);

    // Create a beautiful HTML template
    const html = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>MediKiosk SIH Report</title>
        <style>
            :root {
                --primary: #2563eb; /* A nice modern blue */
                --text-main: #1f2937;
                --bg-main: #ffffff;
                --gray-light: #f3f4f6;
                --border-color: #e5e7eb;
            }
            @page {
                size: A4;
                margin: 20mm;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                color: var(--text-main);
                background: var(--bg-main);
                line-height: 1.6;
                font-size: 11pt;
                margin: 0;
                padding: 0;
            }
            h1, h2, h3, h4, h5 {
                color: var(--primary);
                margin-top: 1.5em;
                margin-bottom: 0.5em;
                font-weight: 700;
            }
            h1 {
                font-size: 26pt;
                text-align: center;
                border-bottom: 3px solid var(--primary);
                padding-bottom: 0.3em;
                margin-bottom: 1.5em;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            h2 {
                font-size: 16pt;
                border-bottom: 1.5px solid var(--border-color);
                padding-bottom: 0.3em;
            }
            h3 {
                font-size: 14pt;
                color: #374151;
            }
            p {
                margin: 0.5em 0 1em 0;
                text-align: justify;
            }
            ul, ol {
                margin: 0.5em 0 1em 0;
                padding-left: 2em;
            }
            li {
                margin-bottom: 0.4em;
            }
            strong {
                color: #111827;
                font-weight: 700;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 1.5em 0;
                font-size: 10pt;
            }
            th, td {
                border: 1px solid var(--border-color);
                padding: 10px 12px;
                text-align: left;
            }
            th {
                background-color: var(--primary);
                color: white;
                font-weight: bold;
                text-transform: uppercase;
                font-size: 9pt;
            }
            tr:nth-child(even) {
                background-color: var(--gray-light);
            }
            hr {
                border: 0;
                border-top: 1px solid var(--border-color);
                margin: 2em 0;
            }
            .mermaid-container {
                display: flex;
                justify-content: center;
                margin: 2em 0;
            }
            .mermaid {
                background: white;
            }
            pre {
                background-color: var(--gray-light);
                padding: 15px;
                border-radius: 6px;
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
                font-size: 9.5pt;
                overflow-x: auto;
                border: 1px solid var(--border-color);
            }
            code {
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
                background-color: var(--gray-light);
                padding: 2px 4px;
                border-radius: 4px;
                font-size: 9.5pt;
            }
            /* Styling specifically for the header section to look like a title page or elegant header */
            .doc-header {
                text-align: center;
                margin-bottom: 3em;
            }
            .doc-header p {
                text-align: center;
                margin: 0.2em 0;
                color: #4b5563;
            }
            .doc-header strong {
                color: var(--primary);
            }
        </style>
        <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
        <script>
            document.addEventListener("DOMContentLoaded", function() {
                // Find all pre > code.language-mermaid
                const codes = document.querySelectorAll('pre code.language-mermaid');
                codes.forEach(code => {
                    const pre = code.parentNode;
                    const container = document.createElement('div');
                    container.className = 'mermaid-container';
                    
                    const div = document.createElement('div');
                    div.className = 'mermaid';
                    div.textContent = code.textContent;
                    
                    container.appendChild(div);
                    pre.parentNode.replaceChild(container, pre);
                });
                
                mermaid.initialize({ startOnLoad: true, theme: 'default' });
            });
        </script>
    </head>
    <body>
        \${htmlContent}
    </body>
    </html>
    `;

    const htmlPath = '/Users/aarsh/Codes/Medi-Kiosk/pdf_generator/temp.html';
    fs.writeFileSync(htmlPath, html);

    console.log("Launching Puppeteer...");
    const browser = await puppeteer.launch({ headless: 'new' });
    const page = await browser.newPage();
    
    console.log("Loading HTML...");
    await page.goto('file://' + htmlPath, { waitUntil: 'networkidle0' });
    
    // Give mermaid time to render
    console.log("Waiting for Mermaid to render...");
    await new Promise(r => setTimeout(r, 2000));
    
    console.log("Generating PDF...");
    await page.pdf({ 
        path: pdfPath, 
        format: 'A4', 
        printBackground: true,
        displayHeaderFooter: true,
        headerTemplate: '<div></div>',
        footerTemplate: '<div style="font-size: 9px; text-align: center; width: 100%; color: #6b7280; font-family: sans-serif;">Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>',
        margin: {
            top: '20mm',
            bottom: '20mm',
            right: '20mm',
            left: '20mm'
        }
    });
    
    await browser.close();
    console.log('Successfully created PDF at:', pdfPath);
}

generate().catch(console.error);
