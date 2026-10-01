-- Filtro de pandoc para el informe (pautas "El informe escrito", I-32).
--
-- Figuras: "Figura N" en negrita y, debajo, el título en cursiva, ARRIBA
-- de la imagen; debajo de la imagen, "Nota. Elaboración propia."
-- Tablas: "Tabla N" en negrita y el título en cursiva, arriba de la
-- tabla. Numeración correlativa en todo el documento.
--
-- Los estilos "Leyenda de figura", "Figura" y "Nota de figura" vienen
-- de scripts/informe_referencia.docx.

local nfig, ntab = 0, 0

-- Bloques `::: revisar`: secciones a cargo del compañero, que se dejan tal
-- cual y salen resaltadas en amarillo (estilo de carácter "Resaltado").
local function resaltar(bloques)
  return pandoc.walk_block(pandoc.Div(bloques), {
    Para = function(p) return pandoc.Para({pandoc.Span(p.content, {["custom-style"] = "Resaltado"})}) end,
    Plain = function(p) return pandoc.Plain({pandoc.Span(p.content, {["custom-style"] = "Resaltado"})}) end,
  }).content
end

function Div(d)
  if d.classes:includes("revisar") then
    return resaltar(d.content)
  end
end

local function div(bloques, estilo)
  return pandoc.Div(bloques, {["custom-style"] = estilo})
end

local function leyenda(rotulo, titulo_inlines)
  return {
    div({pandoc.Para({pandoc.Strong({pandoc.Str(rotulo)})})}, "Leyenda de figura"),
    div({pandoc.Para({pandoc.Emph(titulo_inlines)})}, "Leyenda de figura"),
  }
end

function Figure(fig)
  nfig = nfig + 1
  local titulo = pandoc.utils.blocks_to_inlines(fig.caption.long)
  local out = leyenda("Figura " .. nfig, titulo)
  table.insert(out, div(fig.content, "Figura"))
  table.insert(out, div({pandoc.Para({
    pandoc.Emph({pandoc.Str("Nota.")}), pandoc.Space(),
    pandoc.Str("Elaboración"), pandoc.Space(), pandoc.Str("propia."),
  })}, "Nota de figura"))
  return out
end

function Table(tbl)
  if #tbl.caption.long == 0 then
    return nil
  end
  ntab = ntab + 1
  local titulo = pandoc.utils.blocks_to_inlines(tbl.caption.long)
  tbl.caption.long = {}
  local out = leyenda("Tabla " .. ntab, titulo)
  table.insert(out, tbl)
  return out
end

-- Fragmentos de código con `fuente="ruta"` en sus atributos: van dentro
-- de una tabla de una sola celda con borde y fondo gris (Google Docs
-- descarta los bordes de párrafo al importar), y debajo llevan un
-- epígrafe con el archivo del que se tomaron.
local function xml_escape(t)
  return (t:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

local function recuadro(codigo)
  local borde = '<w:%s w:val="single" w:sz="6" w:space="0" w:color="8C8C8C"/>'
  local bordes = ""
  for _, lado in ipairs({"top", "left", "bottom", "right"}) do
    bordes = bordes .. borde:format(lado)
  end
  local parrafos = {}
  for linea in (codigo .. "\n"):gmatch("(.-)\n") do
    table.insert(parrafos,
      '<w:p><w:pPr><w:spacing w:before="0" w:after="0"/><w:jc w:val="left"/></w:pPr>'
      .. '<w:r><w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" w:cs="Courier New"/>'
      .. '<w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">' .. xml_escape(linea)
      .. '</w:t></w:r></w:p>')
  end
  return '<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>' .. bordes
    .. '</w:tblBorders><w:tblCellMar><w:top w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
    .. '<w:bottom w:w="80" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar></w:tblPr>'
    .. '<w:tblGrid><w:gridCol w:w="9070"/></w:tblGrid><w:tr><w:trPr><w:cantSplit/></w:trPr><w:tc><w:tcPr><w:tcW w:w="5000" w:type="pct"/>'
    .. '<w:shd w:val="clear" w:color="auto" w:fill="F4F4F4"/></w:tcPr>'
    .. table.concat(parrafos) .. '</w:tc></w:tr></w:tbl>'
end

function CodeBlock(cb)
  local fuente = cb.attributes["fuente"]
  if not fuente then
    return nil
  end
  return {
    pandoc.RawBlock("openxml", recuadro(cb.text)),
    div({pandoc.Para({
      pandoc.Emph({pandoc.Str("Fragmento"), pandoc.Space(), pandoc.Str("de")}), pandoc.Space(),
      pandoc.Code(fuente), pandoc.Str("."),
    })}, "Nota de figura"),
  }
end
