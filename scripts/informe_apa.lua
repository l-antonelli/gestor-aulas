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
