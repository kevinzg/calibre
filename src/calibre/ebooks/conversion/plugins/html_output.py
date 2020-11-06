

__license__ = 'GPL 3'
__copyright__ = '2010, Fabian Grassl <fg@jusmeum.de>'
__docformat__ = 'restructuredtext en'

import os, re, shutil
from os.path import dirname, abspath, relpath as _relpath, exists, basename

from calibre.customize.conversion import OutputFormatPlugin, OptionRecommendation
from calibre import CurrentDir
from calibre.ptempfile import PersistentTemporaryDirectory
from polyglot.builtins import unicode_type


def relpath(*args):
    return _relpath(*args).replace(os.sep, '/')


def rename_extension_to_html(href):
    if href.startswith('https://') or href.startswith('http://'):
        return href
    return re.sub(r'\.x(?:ht)?ml(#.*)?$', '.html\g<1>', href)

class HTMLOutput(OutputFormatPlugin):

    name = 'HTML Output'
    author = 'Fabian Grassl'
    file_type = 'htmldir'
    commit_name = 'htmldir_output'

    options = {
        OptionRecommendation(name='template_css',
            help=_('CSS file used for the output instead of the default file')),

        OptionRecommendation(name='template_html_index',
            help=_('Template used for generation of the HTML index file instead of the default file')),

        OptionRecommendation(name='template_html',
            help=_('Template used for the generation of the HTML contents of the book instead of the default file')),

        OptionRecommendation(name='extract_to',
            help=_('Extract the contents of the generated ZIP file to the '
                'specified directory. WARNING: The contents of the directory '
                'will be deleted.')
        ),
    }

    recommendations = {('pretty_print', True, OptionRecommendation.HIGH)}

    def generate_toc(self, oeb_book, ref_url, output_dir):
        '''
        Generate table of contents
        '''
        from lxml import etree
        from polyglot.urllib import unquote

        from calibre.ebooks.oeb.base import element
        from calibre.utils.cleantext import clean_xml_chars
        with CurrentDir(output_dir):
            def build_node(current_node, parent=None):
                if parent is None:
                    parent = etree.Element('ul')
                elif len(current_node.nodes):
                    parent = element(parent, ('ul'))
                for node in current_node.nodes:
                    point = element(parent, 'li')
                    href = relpath(abspath(unquote(node.href)), dirname(ref_url))
                    if isinstance(href, bytes):
                        href = href.decode('utf-8')
                    href = rename_extension_to_html(href)
                    link = element(point, 'a', href=clean_xml_chars(href))
                    title = node.title
                    if isinstance(title, bytes):
                        title = title.decode('utf-8')
                    if title:
                        title = re.sub(r'\s+', ' ', title)
                    link.text = clean_xml_chars(title)
                    build_node(node, point)
                return parent
            wrap = etree.Element('div')
            wrap.append(build_node(oeb_book.toc))
            return wrap

    def generate_html_toc(self, oeb_book, ref_url, output_dir):
        from lxml import etree

        root = self.generate_toc(oeb_book, ref_url, output_dir)
        return etree.tostring(root, pretty_print=True, encoding='unicode',
                xml_declaration=False)

    def convert(self, oeb_book, output_path, input_plugin, opts, log):
        from lxml import etree
        from calibre.utils import zipfile
        from templite import Templite
        from polyglot.urllib import unquote
        from calibre.ebooks.html.meta import EasyMeta

        # read template files
        if opts.template_html_index is not None:
            with open(opts.template_html_index, 'rb') as f:
                template_html_index_data = f.read()
        else:
            template_html_index_data = P('templates/html_export_default_index.tmpl', data=True)

        if opts.template_html is not None:
            with open(opts.template_html, 'rb') as f:
                template_html_data = f.read()
        else:
            template_html_data = P('templates/html_export_default.tmpl', data=True)

        if opts.template_css is not None:
            with open(opts.template_css, 'rb') as f:
                template_css_data = f.read()
        else:
            template_css_data = P('templates/html_export_default.css', data=True)

        template_html_index_data = template_html_index_data.decode('utf-8')
        template_html_data = template_html_data.decode('utf-8')
        template_css_data = template_css_data.decode('utf-8')

        self.log  = log
        self.opts = opts
        meta = EasyMeta(oeb_book.metadata)

        tempdir = os.path.realpath(PersistentTemporaryDirectory())
        output_dir = tempdir
        output_file = os.path.join(tempdir, 'index.html')

        css_path = output_dir+os.sep+'calibreHtmlOutBasicCss.css'
        with open(css_path, 'wb') as f:
            f.write(template_css_data.encode('utf-8'))

        with open(output_file, 'wb') as f:
            html_toc = self.generate_html_toc(oeb_book, output_file, output_dir)
            templite = Templite(template_html_index_data)
            nextLink = oeb_book.spine[0].href
            nextLink = relpath(output_dir+os.sep+nextLink, dirname(output_file))
            cssLink = relpath(abspath(css_path), dirname(output_file))
            tocUrl = relpath(output_file, dirname(output_file))
            t = templite.render(has_toc=bool(oeb_book.toc.count()),
                    toc=html_toc, meta=meta, nextLink=nextLink,
                    tocUrl=tocUrl, cssLink=cssLink,
                    firstContentPageLink=nextLink)
            if isinstance(t, unicode_type):
                t = t.encode('utf-8')
            f.write(t)

        metadata_path = os.path.join(output_dir, 'metadata.json')
        with open(metadata_path, mode='wt') as f:
            import json
            json.dump(list(iter(meta)), f)

        with CurrentDir(output_dir):
            for item in oeb_book.manifest:
                path = abspath(unquote(item.href))
                dir = dirname(path)
                if not exists(dir):
                    os.makedirs(dir)
                if item.spine_position is not None:
                    with open(path, 'wb') as f:
                        pass
                else:
                    with open(path, 'wb') as f:
                        f.write(item.bytes_representation)
                    item.unload_data_from_memory(memory=path)

            for item in oeb_book.spine:
                path = abspath(unquote(item.href))
                dir = dirname(path)
                root = item.data.getroottree()

                # get & clean HTML <HEAD>-data
                head = root.xpath('//h:head', namespaces={'h': 'http://www.w3.org/1999/xhtml'})[0]
                head_content = etree.tostring(head, pretty_print=True, encoding='unicode')
                head_content = re.sub(r'\<\/?head.*\>', '', head_content)
                head_content = re.sub(re.compile(r'\<style.*\/style\>', re.M|re.S), '', head_content)
                head_content = re.sub(r'<(title)([^>]*)/>', r'<\1\2></\1>', head_content)

                # Rename internal links ending with .xhtml to just .html
                links = root.xpath('//h:a', namespaces={'h': 'http://www.w3.org/1999/xhtml'})
                for link in links:
                    if 'href' in link.attrib:
                        href = link.attrib['href']
                        link.attrib['href'] = rename_extension_to_html(href)

                # get & clean HTML <BODY>-data
                body = root.xpath('//h:body', namespaces={'h': 'http://www.w3.org/1999/xhtml'})[0]
                ebook_content = etree.tostring(body, pretty_print=True, encoding='unicode')
                ebook_content = re.sub(r'\<\/?body.*\>', '', ebook_content)
                ebook_content = re.sub(r'<(div|a|span)([^>]*)/>', r'<\1\2></\1>', ebook_content)

                # generate link to next page
                if item.spine_position+1 < len(oeb_book.spine):
                    nextLink = oeb_book.spine[item.spine_position+1].href
                    nextLink = rename_extension_to_html(nextLink)
                    nextLink = relpath(abspath(nextLink), dir)
                else:
                    nextLink = None

                # generate link to previous page
                if item.spine_position > 0:
                    prevLink = oeb_book.spine[item.spine_position-1].href
                    prevLink = rename_extension_to_html(prevLink)
                    prevLink = relpath(abspath(prevLink), dir)
                else:
                    prevLink = None

                cssLink = relpath(abspath(css_path), dir)
                tocUrl = relpath(output_file, dir)
                firstContentPageLink = rename_extension_to_html(oeb_book.spine[0].href)

                # render template
                templite = Templite(template_html_data)
                toc = lambda: self.generate_html_toc(oeb_book, path, output_dir)
                t = templite.render(ebookContent=ebook_content,
                        prevLink=prevLink, nextLink=nextLink,
                        has_toc=False, toc=toc,
                        tocUrl=tocUrl, head_content=head_content,
                        meta=meta, cssLink=cssLink,
                        firstContentPageLink=firstContentPageLink)

                # write html to file
                with open(rename_extension_to_html(path), 'wb') as f:
                    f.write(t.encode('utf-8'))
                item.unload_data_from_memory(memory=path)

                # Remove the original file
                os.remove(path)

        # Remove '.htmldir' from the output path
        assert output_path.endswith('.' + self.file_type)
        suffix_len = 1 + len(self.file_type)
        output_path = output_path[:-suffix_len]

        os.makedirs(output_path, exist_ok=True)

        for file in os.listdir(output_dir):
            shutil.move(
                os.path.join(output_dir, file),
                output_path,
            )

        # cleanup temp dir
        shutil.rmtree(tempdir)
